from __future__ import annotations

from pathlib import Path
import cv2
import numpy as np
import pytest

import capiot.utils.check_image_similarity as image_similarity


def save_image(path: Path, arr: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert arr.dtype == np.uint8 and arr.ndim == 2
    ok = cv2.imwrite(str(path), arr)
    assert ok, f"failed to write {path}"
    return path

def gradient(h: int, w: int) -> np.ndarray:
    return np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))


def test_compare_images_identical_returns_one(tmp_path: Path):
    img = gradient(60, 80)
    p1 = save_image(tmp_path / "a.png", img)
    p2 = save_image(tmp_path / "b.png", img.copy())

    score = image_similarity.compare_images(str(p1), str(p2), crop_params=None)
    assert pytest.approx(score, abs=1e-6) == 1.0


def test_compare_images_crop_region_identical_even_if_outside_differs(tmp_path: Path):
    h, w = 60, 80
    img1 = gradient(h, w)
    img2 = img1.copy()
    # change an area OUTSIDE crop
    img2[:10, :10] = 255

    p1 = save_image(tmp_path / "a.png", img1)
    p2 = save_image(tmp_path / "b.png", img2)

    crop = {"x": 20, "y": 20, "width": 30, "height": 20}
    score = image_similarity.compare_images(str(p1), str(p2), crop_params=crop)
    assert pytest.approx(score, abs=1e-6) == 1.0


def test_compare_images_resizes_img2_when_crop_oob_then_compares(tmp_path: Path, caplog):
    # img1 bigger than img2; crop valid on img1, OOB on img2 -> triggers resize fallback
    img1 = gradient(60, 80)   # H=60, W=80
    img2_small = gradient(30, 40)  # H=30, W=40

    p1 = save_image(tmp_path / "big.png", img1)
    p2 = save_image(tmp_path / "small.png", img2_small)

    # Valid for big (x+w=55<=80, y+h=25<=60), OOB for small (x+w=55>40)
    crop = {"x": 25, "y": 5, "width": 30, "height": 20}

    caplog.set_level("DEBUG", logger="capiot.image")
    score = image_similarity.compare_images(str(p1), str(p2), crop_params=crop)

    # After resizing, the cropped regions should be very similar (linear gradient + linear interp)
    assert 0.95 <= score <= 1.0
    assert any("img2 crop oob; resizing img2 to img1's size" in r.message.lower() for r in caplog.records)



def test_compare_images_mismatch_no_crop_triggers_resize(tmp_path: Path, caplog):
    img1 = gradient(50, 70)
    img2 = gradient(40, 60)
    p1 = save_image(tmp_path / "a.png", img1)
    p2 = save_image(tmp_path / "b.png", img2)

    caplog.set_level("DEBUG", logger="capiot.image")
    _ = image_similarity.compare_images(str(p1), str(p2), crop_params=None)
    assert any("shapes differ after crop; resizing img2" in r.message.lower() for r in caplog.records)


def test_compare_images_file_not_found_raises(tmp_path: Path):
    img = gradient(40, 40)
    p1 = save_image(tmp_path / "a.png", img)
    with pytest.raises(FileNotFoundError):
        image_similarity.compare_images(str(p1), str(tmp_path / "missing.png"), crop_params=None)


def test_compare_images_invalid_crop_missing_keys_raises(tmp_path: Path):
    img = gradient(40, 40)
    p1 = save_image(tmp_path / "a.png", img)
    p2 = save_image(tmp_path / "b.png", img)
    with pytest.raises(ValueError) as e:
        image_similarity.compare_images(str(p1), str(p2), crop_params={"x": 0, "y": 0, "width": 10})  # no height
    assert "missing keys" in str(e.value).lower()


def test_compare_images_invalid_crop_negative_dims_raises(tmp_path: Path):
    img = gradient(40, 40)
    p1 = save_image(tmp_path / "a.png", img)
    p2 = save_image(tmp_path / "b.png", img)
    bad = {"x": -1, "y": 0, "width": 10, "height": 10}
    with pytest.raises(ValueError):
        image_similarity.compare_images(str(p1), str(p2), crop_params=bad)


def test_compare_images_crop_oob_same_shape_raises(tmp_path: Path):
    # When images are same shape and crop is OOB for img1, it should raise immediately
    img = gradient(40, 40)
    p1 = save_image(tmp_path / "a.png", img)
    p2 = save_image(tmp_path / "b.png", img)
    bad_crop = {"x": 1000, "y": 0, "width": 10, "height": 10}
    with pytest.raises(ValueError) as e:
        image_similarity.compare_images(str(p1), str(p2), crop_params=bad_crop)
    assert "out of bounds" in str(e.value).lower()


def test_validate_and_crop_requires_ints(tmp_path: Path):
    img = gradient(20, 30)
    # non-integer that can't be cast
    with pytest.raises(ValueError) as e:
        image_similarity._validate_and_crop(img, {"x": "ten", "y": 0, "width": 5, "height": 5}, origin="img1")
    assert "must be integers" in str(e.value).lower()


# ---------- internal helpers ----------

def test_resize_identity_when_same_size():
    arr = gradient(20, 30)
    out = image_similarity._resize(arr, (20, 30))
    assert out is arr  # function returns the same object when sizes match


def test_validate_and_crop_shape(tmp_path: Path):
    img = gradient(40, 60)
    crop = {"x": 10, "y": 5, "width": 20, "height": 7}
    sub = image_similarity._validate_and_crop(img, crop, origin="img1")
    assert sub.shape == (7, 20)
