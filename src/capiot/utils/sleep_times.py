from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Dict
import logging
import yaml
from typing import Dict, Optional, Union

logger = logging.getLogger("capiot.sleep_times")

@dataclass
class _Cache:
    last_modified_time: float = -1.0
    parsed_values: Dict[str, float] | None = None


class SleepTimes:
    """
    Hot-reloading sleep times (seconds only).
    File must be YAML mapping: key -> number of seconds.
    Example:
        start_app: 3
        after_tap: 1
        trial_cooldown: 30
    If `path` is None, lookups always return the provided default.
    """
    def __init__(self, path: Optional[Union[str, Path]]):
        self.path: Optional[Path] = Path(path) if path else None
        self._cache = _Cache()
        self._lock = RLock()
        if self.path is None:
            logger.debug("SleepTimes initialized with no file (defaults only)")
        else:
            logger.debug("SleepTimes file set to %s", self.path)

    def _load_if_file_changed(self) -> None:
        with self._lock:
            if self.path is None:
                if self._cache.parsed_values is None:
                    self._cache = _Cache(last_modified_time=-1.0, parsed_values={})
                return

            try:
                current_modified_time = self.path.stat().st_mtime
            except FileNotFoundError:
                if self._cache.parsed_values is None or self._cache.last_modified_time != -1.0:
                    logger.warning("SleepTimes file not found: %s (defaults will be used)", self.path)
                self._cache = _Cache(last_modified_time=-1.0, parsed_values={})
                return

            if (
                current_modified_time == self._cache.last_modified_time
                and self._cache.parsed_values is not None
            ):
                return

            raw_text = self.path.read_text(encoding="utf-8")
            raw = yaml.safe_load(raw_text) or {}

            if not isinstance(raw, dict):
                raise ValueError(
                    f"Sleep times file {self.path} must be a mapping, got {type(raw).__name__}"
                )

            parsed: Dict[str, float] = {}
            for key, value in raw.items():
                if not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Sleep time for '{key}' must be a number of seconds, got {value!r}"
                    )
                parsed[str(key)] = float(value)

            self._cache = _Cache(
                last_modified_time=current_modified_time,
                parsed_values=parsed,
            )
            logger.debug("Loaded %d sleep time entries from %s", len(parsed), self.path)



    def get(self, key: str, default: float = 10.0) -> float:
        """
        Return the value for `key` in seconds. If no file is configured or the key
        is missing, return `default`.
        """
        self._load_if_file_changed()
        data = self._cache.parsed_values or {}
        return float(data.get(key, default))
