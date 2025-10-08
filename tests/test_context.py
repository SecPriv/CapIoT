from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import capiot.context as ctx
import capiot.config as cfg


class FixedNow:
    @classmethod
    def now(cls):
        class _DT:
            @staticmethod
            def strftime(fmt: str) -> str:
                return "2025-01-02_03-04"
        return _DT()


class FakeSleepTimes:
    inits: list[Path | None] = []

    def __init__(self, path: Path | None):
        FakeSleepTimes.inits.append(path)

    def get(self, key: str, default: float = 10.0) -> float:
        return default


def make_valid_lan_android(tmp_path: Path) -> cfg.LanProfileConfig:
    """Create a minimally valid LanProfileConfig (android) with real files/dirs."""
    out = tmp_path / "out"
    out.mkdir()

    tap = tmp_path / "tap.json"
    tap.write_text("{}", encoding="utf-8")

    crop = tmp_path / "crop.json"
    crop.write_text("{}", encoding="utf-8")

    up = tmp_path / "up.sh"
    up.write_text("", encoding="utf-8")

    down = tmp_path / "down.sh"
    down.write_text("", encoding="utf-8")

    btlog = tmp_path / "bt.log"
    btlog.write_text("", encoding="utf-8")

    android = cfg.AndroidConfig(
        pcapdroid_api_key="k",
        pcap_download_path=out,
        bluetooth_log_path=btlog,
    )

    return cfg.LanProfileConfig(
        network_profile="lan",
        platform="android",
        server_interface="eth0",
        phone_interface="usb0",
        output_path=out,
        tap_coordinates_path=tap,
        image_crop_regions_path=crop,
        iptables_script_up_path=up,
        iptables_script_down_path=down,
        android=android,
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Lamp 2000", "Lamp_2000"),
        ("weird/name?", "weird_name"),
        ("...hidden...", "hidden"),
        ("", "device"),
        ("💡-smart!plug*", "-smart_plug"),
        ("a b\tc\nd", "a_b_c_d"),
        ("a..b--c", "a..b--c"),
    ],
)
def test_safe_filename(name, expected):
    assert ctx._safe_filename(name) == expected


def test_create_builds_expected_folders(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ctx, "datetime", FixedNow)

    appcfg = make_valid_lan_android(tmp_path)
    ec = ctx.ExperimentContext.create(
        config=appcfg,
        package_name="com.example.app",
        phone_id="PHONE1",
        device_name="Lamp 2000",
    )

    expected_root = appcfg.output_path / "Lamp_2000" / "2025-01-02_03-04"
    assert ec.experiment_path == expected_root

    for sub in ["frida", "no_frida", "mitm", "sslkeys"]:
        p = expected_root / sub
        assert p.exists() and p.is_dir()

    assert ec.package_name == "com.example.app"
    assert ec.phone_id == "PHONE1"
    assert ec.device_name == "Lamp 2000"



def test_create_raises_runtimeerror_when_mkdir_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ctx, "datetime", FixedNow)
    appcfg = make_valid_lan_android(tmp_path)

    expected_root = appcfg.output_path / "Lamp_2000" / "2025-01-02_03-04"
    expected_root.parent.mkdir(parents=True, exist_ok=True)
    expected_root.write_text("I am a file, not a dir", encoding="utf-8")

    with pytest.raises(RuntimeError) as e:
        ctx.ExperimentContext.create(appcfg, "pkg", "ph", "Lamp 2000")
    assert "Failed to create experiment directories" in str(e.value)


def test_sleep_times_path_none_and_lazy_singleton(tmp_path: Path, monkeypatch):
    ec = ctx.ExperimentContext.model_construct(
        package_name="pkg",
        phone_id="ph",
        device_name="dev",
        config=SimpleNamespace(output_path=tmp_path, sleep_times_path=None),
        experiment_path=tmp_path / "exp",
    )

    monkeypatch.setattr(ctx, "SleepTimes", FakeSleepTimes)

    st1 = ec.sleep_times
    assert isinstance(st1, FakeSleepTimes)
    assert FakeSleepTimes.inits[-1] is None

    st2 = ec.sleep_times
    assert st2 is st1
    assert FakeSleepTimes.inits.count(None) == 1


def test_sleep_times_path_resolves_to_path(tmp_path: Path, monkeypatch):
    sleep_path = tmp_path / "sleep.yaml"
    ec = ctx.ExperimentContext.model_construct(
        package_name="pkg",
        phone_id="ph",
        device_name="dev",
        config=SimpleNamespace(output_path=tmp_path, sleep_times_path=str(sleep_path)),
        experiment_path=tmp_path / "exp",
    )

    FakeSleepTimes.inits.clear()
    monkeypatch.setattr(ctx, "SleepTimes", FakeSleepTimes)

    _ = ec.sleep_times
    assert FakeSleepTimes.inits[-1] == sleep_path


def test_record_and_summarise_writes_file(tmp_path: Path):
    exp_dir = tmp_path / "exp"
    exp_dir.mkdir()

    ec = ctx.ExperimentContext.model_construct(
        package_name="pkg",
        phone_id="ph",
        device_name="dev",
        config=SimpleNamespace(output_path=tmp_path, sleep_times_path=None),
        experiment_path=exp_dir,
    )

    ec.record_iteration_result("no_frida", 1, True)
    ec.record_iteration_result("no_frida", 2, False)
    ec.record_iteration_result("no_frida", 3, True)

    ec.record_iteration_result("frida", 1, True)
    ec.record_iteration_result("frida", 2, True)
    ec.record_iteration_result("frida", 3, False)

    summary = ec.summarise_iterations()

    assert summary.splitlines()[0] == "Iteration results"

    canon = re.sub(r"\s+", "", summary)
    assert "no_frida:2/3failed:(2)" in canon
    assert "frida:2/3failed:(3)" in canon

    out = exp_dir / "experiment_summary.txt"
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() == summary.strip()


def test_summarise_write_failure_raises_runtimeerror(tmp_path: Path, monkeypatch):
    exp_dir = tmp_path / "exp"
    exp_dir.mkdir()
    ec = ctx.ExperimentContext.model_construct(
        package_name="pkg",
        phone_id="ph",
        device_name="dev",
        config=SimpleNamespace(output_path=tmp_path, sleep_times_path=None),
        experiment_path=exp_dir,
    )
    ec.record_iteration_result("no_frida", 1, True)

    target = exp_dir / "experiment_summary.txt"
    orig_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if self == target:
            raise OSError("disk full")
        return orig_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    with pytest.raises(RuntimeError) as e:
        ec.summarise_iterations()

    assert "Failed to write iteration summary" in str(e.value)
