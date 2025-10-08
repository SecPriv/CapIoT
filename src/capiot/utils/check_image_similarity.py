import cv2
from skimage import metrics
import logging
from pathlib import Path
import numpy as np
from typing import Mapping, Optional

logger = logging.getLogger("capiot.image")

def _load_image_gray(image_path: str | Path) -> np.ndarray:
    """
    Load an image as grayscale (uint8). Raises FileNotFoundError if unreadable.
    """
    p = Path(image_path)
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {p}")
    logger.debug("Loaded image %s with shape=%s", p, img.shape)
    return img


def _validate_and_crop(img: np.ndarray, crop: Mapping[str, int], *, origin: str) -> np.ndarray:
    """
    Validate crop dict and return the cropped view.
    """
    req = ("x", "y", "width", "height")
    missing = [k for k in req if k not in crop]
    if missing:
        raise ValueError(f"crop_params missing keys: {', '.join(missing)}")

    try:
        x = int(crop["x"])
        y = int(crop["y"])
        w = int(crop["width"])
        h = int(crop["height"])
    except Exception as e:
        raise ValueError(f"crop_params must be integers (x, y, width, height): {crop}") from e

    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ValueError(f"Invalid crop rectangle for {origin}: x={x}, y={y}, w={w}, h={h}")

    H, W = img.shape[:2]
    if x + w > W or y + h > H:
        raise ValueError(
            f"Crop rectangle out of bounds for {origin}: "
            f"(x={x}, y={y}, w={w}, h={h}) on image {W}x{H}"
        )

    cropped = img[y : y + h, x : x + w]
    logger.debug("Cropped %s to [%d:%d, %d:%d] -> shape=%s", origin, y, y + h, x, x + w, cropped.shape)
    return cropped

def _resize(src: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    """
    Resize src to (target_h, target_w) using a sensible interpolation.
    """
    th, tw = target_shape
    sh, sw = src.shape[:2]
    if (sh, sw) == (th, tw):
        return src
    # Downscale -> INTER_AREA; Upscale -> INTER_LINEAR
    interp = cv2.INTER_AREA if (th < sh or tw < sw) else cv2.INTER_LINEAR
    resized = cv2.resize(src, (tw, th), interpolation=interp)
    logger.debug("Resized image %sx%s -> %sx%s (interp=%s)", sw, sh, tw, th, "AREA" if interp==cv2.INTER_AREA else "LINEAR")
    return resized


def _crop_with_resize_fallback(
    img1: np.ndarray,
    img2: np.ndarray,
    crop_params: Mapping[str, int],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Apply the same crop to both images. If the crop is OOB for img2 due to size
    mismatch, first resize img2 to img1's full size then try again.
    """
    img1_cropped = _validate_and_crop(img1, crop_params, origin="img1")
    try:
        img2_cropped = _validate_and_crop(img2, crop_params, origin="img2")
    except ValueError as e:
        if img2.shape != img1.shape:
            logger.debug("img2 crop OOB; resizing img2 to img1's size before cropping")
            img2_resized = _resize(img2, img1.shape[:2])
            img2_cropped = _validate_and_crop(img2_resized, crop_params, origin="img2-resized")
        else:
            raise
    return img1_cropped, img2_cropped


def compare_images(img1_path: str, img2_path: str, crop_params: Optional[Mapping[str, int]]):
    """
    Compute the SSIM score between two images.

    Parameters
    ----------
    img1_path : str
        Path to first image (reference).
    img2_path : str
        Path to second image (candidate).
    crop_params : Mapping[str, int] | None
        Optional dict with keys {x, y, width, height}. If provided, the region
        is compared; otherwise the whole images are compared.

    Returns
    -------
    float
        SSIM score in [-1.0, 1.0], where 1.0 means identical.
    """
    img1_full = _load_image_gray(img1_path)
    img2_full = _load_image_gray(img2_path)

    if crop_params:
        img1, img2 = _crop_with_resize_fallback(img1_full, img2_full, crop_params)
    else:
        img1, img2 = img1_full, img2_full

    if img1.shape != img2.shape:
        logger.debug("Shapes differ after crop; resizing img2 to match img1")
        img2 = _resize(img2, img1.shape[:2])

    score = float(metrics.structural_similarity(img1, img2))
    logger.debug(
        "SSIM(%s vs %s, crop=%s) = %.5f",
        img1_path,
        img2_path,
        bool(crop_params),
        score,
    )
    return score