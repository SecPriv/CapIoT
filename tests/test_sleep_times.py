from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import capiot.utils.sleep_times as st


def write_yaml(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p



def test_defaults_only_when_path_none_returns_default_and_no_warning(caplog):
    caplog.set_level("DEBUG", logger="capiot.sleep_times")
    s = st.SleepTimes(None)
    assert s.get("anything", default=4.2) == 4.2
    assert not any("file not found" in rec.message.lower() for rec in caplog.records)


def test_missing_file_warns_once_and_returns_default(tmp_path: Path, caplog):
    caplog.set_level("WARNING", logger="capiot.sleep_times")
    p = tmp_path / "sleep.yaml"
    s = st.SleepTimes(p)

    v1 = s.get("x", default=1.5)
    assert v1 == 1.5
    assert any("file not found" in rec.message.lower() for rec in caplog.records)

    caplog.clear()
    v2 = s.get("x", default=2.5)
    assert v2 == 2.5
    assert not any("file not found" in rec.message.lower() for rec in caplog.records)


def test_loads_values_casts_to_float_and_logs_count(tmp_path: Path, caplog):
    caplog.set_level("DEBUG", logger="capiot.sleep_times")
    p = write_yaml(tmp_path / "sleep.yaml", "start_app: 3\nafter_tap: 1\ntrial_cooldown: 30\n")
    s = st.SleepTimes(p)
    assert s.get("start_app", default=0.0) == 3.0
    assert s.get("after_tap", default=0.0) == 1.0
    assert s.get("missing_key", default=2.25) == 2.25
    assert any("loaded 3 sleep time entries" in rec.message.lower() for rec in caplog.records)


def test_non_mapping_yaml_raises(tmp_path: Path):
    p = write_yaml(tmp_path / "sleep.yaml", "- 1\n- 2\n")
    s = st.SleepTimes(p)
    with pytest.raises(ValueError) as e:
        s.get("anything")
    assert "must be a mapping" in str(e.value).lower()


def test_non_numeric_value_raises(tmp_path: Path):
    p = write_yaml(tmp_path / "sleep.yaml", "start_app: 'three'\n")
    s = st.SleepTimes(p)
    with pytest.raises(ValueError) as e:
        s.get("start_app")
    assert "must be a number of seconds" in str(e.value).lower()


def test_hot_reload_when_mtime_changes(tmp_path: Path):
    p = write_yaml(tmp_path / "sleep.yaml", "after_tap: 1\n")
    s = st.SleepTimes(p)
    assert s.get("after_tap", default=0.0) == 1.0

    time.sleep(0.02)
    write_yaml(p, "after_tap: 2\n")
    os.utime(p, None)

    assert s.get("after_tap", default=0.0) == 2.0


def test_cache_is_used_when_mtime_unchanged(tmp_path: Path):
    p = write_yaml(tmp_path / "sleep.yaml", "start_app: 3\n")
    s = st.SleepTimes(p)
    assert s.get("start_app", default=0.0) == 3.0

    mtime = p.stat().st_mtime
    write_yaml(p, "start_app: 9\n")
    os.utime(p, (mtime, mtime))

    assert s.get("start_app", default=0.0) == 3.0


def test_delete_file_after_load_warns_and_falls_back_to_default(tmp_path: Path, caplog):
    caplog.set_level("WARNING", logger="capiot.sleep_times")
    p = write_yaml(tmp_path / "sleep.yaml", "trial: 7\n")
    s = st.SleepTimes(p)
    assert s.get("trial", default=0.0) == 7.0

    p.unlink()
    caplog.clear()
    assert s.get("trial", default=1.25) == 1.25
    assert any("file not found" in rec.message.lower() for rec in caplog.records)
