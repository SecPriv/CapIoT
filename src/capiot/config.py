from __future__ import annotations
from typing import Literal, Optional, Union, Annotated
from pathlib import Path
import json, logging

import yaml
from pydantic import BaseModel, Field, ValidationError, TypeAdapter, model_validator, field_validator

logger = logging.getLogger("capiot.config")

Platform = Literal["android", "ios"]
NetworkProfile = Literal["lan", "wan"]

class ConfigLoadError(Exception):
    """Raised when a YAML config cannot be loaded or validated."""


class BaseConfig(BaseModel):
    """Base model that normalizes Paths."""
    model_config = {"validate_default": True, "extra": "allow"}

    @staticmethod
    def _norm_path(p: Optional[Path]) -> Optional[Path]:
        return p.expanduser().resolve() if isinstance(p, Path) else p

    @staticmethod
    def _must_exist_file(p: Path, field_name: str) -> Path:
        if not p.exists():
            logger.error("%s does not exist: %s", field_name, p)
            raise ValueError(f"'{field_name}' does not exist: {p}")
        if not p.is_file():
            logger.error("%s must be a file: %s", field_name, p)
            raise ValueError(f"'{field_name}' must be a file: {p}")
        return p

    @staticmethod
    def _must_exist_dir(p: Path, field_name: str) -> Path:
        if not p.exists():
            logger.error("%s directory does not exist: %s", field_name, p)
            raise ValueError(f"'{field_name}' directory does not exist: {p}")
        if not p.is_dir():
            logger.error("%s must be a directory: %s", field_name, p)
            raise ValueError(f"'{field_name}' must be a directory: {p}")
        return p

class AndroidConfig(BaseConfig):
    pcapdroid_api_key: str
    pcap_download_path: Path
    bluetooth_log_path: Path

class iOSConfig(BaseConfig):
    ssh: SshConnectionConfig
    phone_pcap_save_path: Path

class SshConnectionConfig(BaseConfig):
    host: str
    username: str
    port: int = 22
    key_path: Optional[Path] = None
    password: Optional[str] = None

    @field_validator("key_path")
    @classmethod
    def _normalize_key_path(cls, v: Optional[Path]) -> Optional[Path]:
        if v is not None:
            BaseConfig._must_exist_file(v, "ssh.key_path")
        return v

    @model_validator(mode="after")
    def _require_auth(self) -> "SshConnectionConfig":
        mode = "key" if self.key_path else ("password" if self.password else None)
        if not mode:
            logger.error("SSH auth missing (need key_path or password) for %s@%s", self.username, self.host)
            raise ValueError("Provide either 'key_path' or 'password' for SSH authentication.")
        logger.debug("SSH auth mode: %s (user=%s host=%s)", mode, self.username, self.host)
        return self

class SharedConfig(BaseConfig):
    platform: Platform
    server_interface: str
    phone_interface: str
    output_path: Path
    frida_iterations: int = 10
    no_frida_iterations: int = 10
    image_similarity_threshold: float = 0.99
    tap_coordinates_path: Path
    image_crop_regions_path: Path
    sleep_times_path: Optional[Path] = None
    iptables_script_up_path: Path
    iptables_script_down_path: Path

    @field_validator(
        "output_path",
        "tap_coordinates_path",
        "image_crop_regions_path",
        "sleep_times_path",
        "iptables_script_up_path",
        "iptables_script_down_path",
    )
    @classmethod
    def _normalize_paths(cls, v: Optional[Path]) -> Optional[Path]:
        return BaseConfig._norm_path(v)

    @model_validator(mode="after")
    def _check_required_paths(self) -> "SharedConfig":
        BaseConfig._must_exist_dir(self.tap_coordinates_path, "tap_coordinates_path")
        BaseConfig._must_exist_file(self.image_crop_regions_path, "image_crop_regions_path")
        BaseConfig._must_exist_file(self.iptables_script_up_path, "iptables_script_up_path")
        BaseConfig._must_exist_file(self.iptables_script_down_path, "iptables_script_down_path")

        if self.sleep_times_path is not None:
            BaseConfig._must_exist_file(self.sleep_times_path, "sleep_times_path")

        return self


class LanProfileConfig(SharedConfig):
    """
    Same-network profile.
    """
    network_profile: Literal["lan"] = "lan"
    android: Optional[AndroidConfig] = None
    ios: Optional[iOSConfig] = None

    @model_validator(mode="after")
    def _android_required_for_android_platform(self, m: "LanProfileConfig"):
        if self.platform == "android" and self.android is None:
            raise ValueError("android config is required when platform == 'android'")
        if self.platform != "android" and self.android is not None:
            raise ValueError("android config must be omitted unless platform == 'android'")
        return self

    @model_validator(mode="after")
    def _ios_required_for_ios_platform(self, m: "LanProfileConfig"):
        if self.platform == "ios" and self.ios is None:
            raise ValueError("ios config is required when platform == 'ios'")
        if self.platform != "ios" and self.ios is not None:
            raise ValueError("ios config must be omitted unless platform == 'ios'")
        return self


class WANProfileConfig(SharedConfig):
    """
    Different-network profile (adds remote capture requirements).
    """
    network_profile: Literal["wan"] = "wan"
    remote_server_ssh: SshConnectionConfig
    remote_server_interface: str
    android: Optional[AndroidConfig] = None
    ios: Optional[iOSConfig] = None

    @model_validator(mode="after")
    def _android_required_for_android_platform(self, m: "WANProfileConfig"):
        if self.platform == "android" and self.android is None:
            raise ValueError("android config is required when platform == 'android'")
        if self.platform != "android" and self.android is not None:
            raise ValueError("android config must be omitted unless platform == 'android'")
        return self

    @model_validator(mode="after")
    def _ios_required_for_ios_platform(self, m: "WANProfileConfig"):
        if self.platform == "ios" and self.ios is None:
            raise ValueError("ios config is required when platform == 'ios'")
        if self.platform != "ios" and self.ios is not None:
            raise ValueError("ios config must be omitted unless platform == 'ios'")
        return self

ProfileConfigUnion = Annotated[
    Union[
        LanProfileConfig,
        WANProfileConfig,
    ],
    Field(discriminator="network_profile"),
]

AppConfig = ProfileConfigUnion

def _load_yaml(config_path: str) -> dict:
    """
    Read YAML file, returning a dict.
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        logger.error("Config file not found: %s", path)
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r") as file_obj:
        data = yaml.safe_load(file_obj) or {}
    if not isinstance(data, dict):
        logger.error("Top-level YAML must be a mapping/object (got %s)", type(data).__name__)
        raise ValueError("Top-level YAML must be a mapping/object.")
    logger.debug("Top-level keys: %s", ", ".join(sorted(map(str, data.keys()))))
    return data

def load_config(config_path: str) -> AppConfig:
    """
     Load and validate config based on network_profile.
    Raises ConfigLoadError on failure.
    """
    try:
        raw_config = _load_yaml(config_path)
        profile = raw_config.get("network_profile", "<missing>")
        logger.debug("Validating AppConfig (network_profile=%s)", profile)
        adapter = TypeAdapter(AppConfig)
        return adapter.validate_python(raw_config)
    except (ValidationError, ValueError, FileNotFoundError) as error:
        msg = _format_config_error(error)
        logger.error("Config validation failed:\n%s", msg)
        raise ConfigLoadError(msg) from error

def _format_config_error(error: Exception) -> str:
    header = "Configuration error:\n"
    if isinstance(error, ValidationError):
        lines = []
        for issue in error.errors():
            location = ".".join(str(p) for p in issue.get("loc", []))
            message = issue.get("msg", "Invalid value")
            lines.append(f"  - {location}: {message}")
        return header + "\n".join(lines)
    return header + str(error)


def app_config_json_schema() -> dict:
    """
    Return a pydantic JSON Schema for the AppConfig union.
    """
    return TypeAdapter(AppConfig).json_schema()


def _validate_crop_regions(crop_region: list, device_name: str) -> bool:
    if not isinstance(crop_region, list):
        msg = f"Crop regions for device '{device_name}' must be a list; got {type(crop_region).__name__}"
        logger.warning(msg)
        return False

    for i, region in enumerate(crop_region, 1):
        if not isinstance(region, dict):
            logger.warning("Found non-dict region #%d for '%s': %r", i, device_name, region)
            return False
        try:
            x = int(region["x"])
            y = int(region["y"])
            w = int(region["width"])
            h = int(region["height"])
        except Exception:
            logger.warning("Region #%d for '%s' missing/invalid keys: %r", i, device_name, region)
            return False
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            logger.warning("Region #%d for '%s' has invalid dimensions: %r", i, device_name, region)
            return False

    return True

def load_image_crop_regions(crop_regions_path: Path, device_name: str) -> dict | None:
    """
    Load crop regions JSON and return a list of regions for `device_name`.
    Expected schema:
        { "<device_name>": [ {"x":int,"y":int,"width":int,"height":int}, ... ] }
    Returns None if the file or the device-specific entry is missing/invalid.
    """
    crop_region_path = BaseConfig._norm_path(crop_regions_path)
    if not crop_region_path or not crop_region_path.exists():
        logger.info("Image crop regions file not found: %s", crop_region_path)
        return None
    try:
        with crop_region_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in {crop_region_path}: {e.msg} (line {e.lineno}, col {e.colno})"
        logger.warning(msg)
        return None
    except OSError as e:
        logger.warning("Failed to read image crop regions file %s: %s", crop_region_path, e)
        return None
    entry = data.get(device_name)
    if entry is None:
        logger.warning("No crop regions found for device '%s' in %s", device_name, crop_region_path)
        return None
    if not _validate_crop_regions(entry, device_name):
        logger.warning("No valid crop regions for device '%s' in %s", device_name, crop_region_path)
        return None
    logger.debug("Loaded crop regions for device '%s' from %s", device_name, crop_region_path)
    return entry
