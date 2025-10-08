from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

import capiot.config as cfg


def write(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p

def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    return p


def test_android_paths_are_normalized_and_must_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pcap_dir = tmp_path / "pcaps"
    pcap_dir.mkdir()

    bt_log = tmp_path / "bt.log"
    touch(bt_log)

    android = cfg.AndroidConfig(
        pcapdroid_api_key="secret",
        pcap_download_path=pcap_dir,
        bluetooth_log_path=bt_log,
    )
    assert android.pcap_download_path.resolve() == pcap_dir.resolve()
    assert android.bluetooth_log_path.resolve() == bt_log.resolve()


def test_android_missing_dir_raises(tmp_path: Path):
    missing_dir = tmp_path / "nope"
    bt_log = touch(tmp_path / "bt.log")
    with pytest.raises(ValueError) as e:
        cfg.AndroidConfig(
            pcapdroid_api_key="secret",
            pcap_download_path=missing_dir,
            bluetooth_log_path=bt_log,
        )
    assert "pcap_download_path" in str(e.value)


def test_android_bt_log_must_be_file(tmp_path: Path):
    pcap_dir = tmp_path / "pcaps"
    pcap_dir.mkdir()
    bt_log_dir = tmp_path / "bt_dir"
    bt_log_dir.mkdir()
    with pytest.raises(ValueError) as e:
        cfg.AndroidConfig(
            pcapdroid_api_key="secret",
            pcap_download_path=pcap_dir,
            bluetooth_log_path=bt_log_dir,
        )
    assert "bluetooth_log_path" in str(e.value)


def test_ssh_both_key_and_password_allowed(tmp_path: Path):
    key = touch(tmp_path / "id_rsa")
    ssh = cfg.SshConnectionConfig(host="h", username="u", key_path=key, password="pw")
    assert ssh.key_path == key
    assert ssh.password == "pw"

def test_ssh_requires_either_key_or_password(tmp_path: Path):
    with pytest.raises(ValueError) as e:
        cfg.SshConnectionConfig(host="h", username="u")
    assert "Provide either 'key_path' or 'password'" in str(e.value)


def test_ssh_key_must_exist_and_be_file(tmp_path: Path):
    missing = tmp_path / "id_rsa"
    with pytest.raises(ValueError):
        cfg.SshConnectionConfig(host="h", username="u", key_path=missing)

    key = touch(tmp_path / "id_ok")
    ssh = cfg.SshConnectionConfig(host="h", username="u", key_path=key)
    assert ssh.key_path == key


def test_ssh_password_mode(tmp_path: Path):
    ssh = cfg.SshConnectionConfig(host="h", username="u", password="pw")
    assert ssh.password == "pw"
    assert ssh.key_path is None


def _mk_shared_paths(tmp_path: Path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    tap = touch(tmp_path / "tap.json")
    crop = touch(tmp_path / "crop.json")
    up = touch(tmp_path / "up.sh")
    down = touch(tmp_path / "down.sh")
    return output_dir, tap, crop, up, down

def test_shared_sleep_times_provided_but_missing_raises(tmp_path: Path):
    out, tap, crop, up, down = _mk_shared_paths(tmp_path)
    missing_sleep = tmp_path / "sleep.json"
    with pytest.raises(ValueError) as e:
        cfg.SharedConfig(
            platform="android",
            server_interface="srv0",
            phone_interface="ph0",
            output_path=out,
            tap_coordinates_path=tap,
            image_crop_regions_path=crop,
            sleep_times_path=missing_sleep,
            iptables_script_up_path=up,
            iptables_script_down_path=down,
        )
    assert "sleep_times_path" in str(e.value)

def test_shared_required_paths_and_optional_sleep_times(tmp_path: Path):
    output_dir, tap, crop, up, down = _mk_shared_paths(tmp_path)
    sleep_times = touch(tmp_path / "sleep.json")

    cfg.SharedConfig(
        platform="android",
        server_interface="srv0",
        phone_interface="ph0",
        output_path=output_dir,
        tap_coordinates_path=tap,
        image_crop_regions_path=crop,
        sleep_times_path=sleep_times,
        iptables_script_up_path=up,
        iptables_script_down_path=down,
    )

def test_shared_optional_sleep_times_can_be_none(tmp_path: Path):
    output_dir, tap, crop, up, down = _mk_shared_paths(tmp_path)
    cfg.SharedConfig(
        platform="ios",
        server_interface="srv0",
        phone_interface="ph0",
        output_path=output_dir,
        tap_coordinates_path=tap,
        image_crop_regions_path=crop,
        sleep_times_path=None,
        iptables_script_up_path=up,
        iptables_script_down_path=down,
    )


def test_shared_missing_file_raises(tmp_path: Path):
    output_dir, tap, crop, up, _down = _mk_shared_paths(tmp_path)
    missing_down = tmp_path / "missing.sh"
    with pytest.raises(ValueError) as e:
        cfg.SharedConfig(
            platform="ios",
            server_interface="srv0",
            phone_interface="ph0",
            output_path=output_dir,
            tap_coordinates_path=tap,
            image_crop_regions_path=crop,
            iptables_script_up_path=up,
            iptables_script_down_path=missing_down,
        )
    assert "iptables_script_down_path" in str(e.value)

def _yaml(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


def test_load_config_lan_android_ok(tmp_path: Path):
    out, tap, crop, up, down = _mk_shared_paths(tmp_path)
    bt = touch(tmp_path / "bt.log")

    y = f"""
    network_profile: lan
    platform: android
    server_interface: eth0
    phone_interface: usb0
    output_path: {out}
    tap_coordinates_path: {tap}
    image_crop_regions_path: {crop}
    iptables_script_up_path: {up}
    iptables_script_down_path: {down}
    android:
      pcapdroid_api_key: abc
      pcap_download_path: {out}
      bluetooth_log_path: {bt}
    """
    path = _yaml(tmp_path / "lan.yaml", y)
    conf = cfg.load_config(str(path))
    assert isinstance(conf, cfg.LanProfileConfig)
    assert conf.network_profile == "lan"
    assert conf.platform == "android"
    assert conf.android is not None
    assert conf.ios is None


def test_load_config_lan_ios_requires_ios_block(tmp_path: Path):
    out, tap, crop, up, down = _mk_shared_paths(tmp_path)

    y = f"""
    network_profile: lan
    platform: ios
    server_interface: eth0
    phone_interface: ph0
    output_path: {out}
    tap_coordinates_path: {tap}
    image_crop_regions_path: {crop}
    iptables_script_up_path: {up}
    iptables_script_down_path: {down}
    """
    p = _yaml(tmp_path / "lan_ios_missing.yaml", y)
    with pytest.raises(cfg.ConfigLoadError) as e:
        cfg.load_config(str(p))
    assert "Configuration error:" in str(e.value)
    assert "ios config is required" in str(e.value)

def test_wan_android_platform_requires_android_block(tmp_path: Path):
    out, tap, crop, up, down = _mk_shared_paths(tmp_path)
    key = touch(tmp_path / "id_rsa")
    y = f"""
    network_profile: wan
    platform: android
    server_interface: eth0
    phone_interface: ph0
    output_path: {out}
    tap_coordinates_path: {tap}
    image_crop_regions_path: {crop}
    iptables_script_up_path: {up}
    iptables_script_down_path: {down}
    remote_server_interface: ens3
    remote_server_ssh:
      host: example.com
      username: root
      key_path: {key}
    """
    p = _yaml(tmp_path / "wan_android_missing_android.yaml", y)
    with pytest.raises(cfg.ConfigLoadError) as e:
        cfg.load_config(str(p))
    assert "android config is required" in str(e.value)



def test_load_config_wan_ok_with_remote_ssh_key(tmp_path: Path):
    out, tap, crop, up, down = _mk_shared_paths(tmp_path)
    key = touch(tmp_path / "id_rsa")

    y = f"""
    network_profile: wan
    platform: ios
    server_interface: eth0
    phone_interface: ph0
    output_path: {out}
    tap_coordinates_path: {tap}
    image_crop_regions_path: {crop}
    iptables_script_up_path: {up}
    iptables_script_down_path: {down}
    remote_server_interface: ens3
    remote_server_ssh:
      host: example.com
      username: root
      key_path: {key}
    ios:
      ssh:
        host: iphone.local
        username: mobile
        password: secret
    """
    p = _yaml(tmp_path / "wan.yaml", y)
    conf = cfg.load_config(str(p))
    assert isinstance(conf, cfg.WANProfileConfig)
    assert conf.remote_server_interface == "ens3"
    assert conf.remote_server_ssh.username == "root"
    assert conf.ios is not None
    assert conf.android is None

def test_load_config_non_mapping_yaml_is_wrapped(tmp_path: Path):
    p = _yaml(tmp_path / "bad.yaml", " - a\n - b\n")
    with pytest.raises(cfg.ConfigLoadError) as e:
        cfg.load_config(str(p))
    s = str(e.value)
    assert "Top-level YAML must be a mapping/object" in s

def test_load_config_file_not_found_is_wrapped(tmp_path: Path):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(cfg.ConfigLoadError) as e:
        cfg.load_config(str(missing))
    s = str(e.value)
    assert "Configuration error:" in s
    assert "Config file not found" in s


def test_app_config_json_schema_is_dict():
    schema = cfg.app_config_json_schema()
    assert isinstance(schema, dict)
    assert schema


def test_load_image_crop_regions_missing_file_returns_none(tmp_path: Path, caplog):
    p = tmp_path / "missing.json"
    result = cfg.load_image_crop_regions(p, "meross")
    assert result is None


def test_load_image_crop_regions_invalid_json(tmp_path: Path):
    p = write(tmp_path / "bad.json", "{ not: json")
    result = cfg.load_image_crop_regions(p, "anything")
    assert result is None


def test_load_image_crop_regions_missing_device_entry(tmp_path: Path):
    p = write(tmp_path / "crop.json", json.dumps({"OtherDevice": {"x": 1}}))
    result = cfg.load_image_crop_regions(p, "MyDevice")
    assert result is None


def test_load_image_crop_regions_ok(tmp_path: Path):
    payload = {"MyDevice": [{"x": 1, "y": 2, "height": 3, "width": 4}]}
    p = write(tmp_path / "crop.json", json.dumps(payload))
    result = cfg.load_image_crop_regions(p, "MyDevice")
    assert result == payload["MyDevice"]


def test_load_image_crop_regions_directory_oserror_returns_none(tmp_path: Path):
    d = tmp_path / "dir_as_file"
    d.mkdir()
    result = cfg.load_image_crop_regions(d, "device")
    assert result is None


def test_load_image_crop_regions_device_entry_not_dict(tmp_path: Path):
    data = {"Dev": ["not", "a", "dict"]}
    p = tmp_path / "crop.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert cfg.load_image_crop_regions(p, "Dev") is None


def test_load_image_crop_regions_logs_on_missing_file(tmp_path: Path, caplog):
    caplog.set_level("INFO", logger="capiot.config")
    p = tmp_path / "nope.json"
    _ = cfg.load_image_crop_regions(p, "X")
    assert any("Image crop regions file not found" in r.message for r in caplog.records)


def test_load_image_crop_regions_logs_on_invalid_json(tmp_path: Path, caplog):
    caplog.set_level("WARNING", logger="capiot.config")
    p = tmp_path / "bad.json"
    p.write_text("{ invalid", encoding="utf-8")
    _ = cfg.load_image_crop_regions(p, "X")
    assert any("Invalid JSON" in r.message for r in caplog.records)