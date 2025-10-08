from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, PrivateAttr
from collections import defaultdict
import logging, re

from .utils.sleep_times import SleepTimes

logger = logging.getLogger("capiot.context")

class ExperimentError(RuntimeError):
    """Raised when an experiment fails."""

def _safe_filename(name: str) -> str:
    """
    Make a filesystem-safe path segment.
    Keeps letters, numbers, _, -, . ; collapses others to '_'.
    """
    s = re.sub(r"[^\w\-.]+", "_", name).strip("._")
    return s or "device"

class ExperimentContext(BaseModel):
    package_name: str
    phone_id: str
    device_name: str
    config: "AppConfig" = Field(repr=False)
    experiment_path: Path

    _iteration_results = PrivateAttr(
        default_factory=lambda: defaultdict(list)
    )

    _sleep_times_manager: SleepTimes | None = PrivateAttr(default=None)

    @classmethod
    def create(
        cls,
        config: "AppConfig",
        package_name: str,
        phone_id: str,
        device_name: str
    ) -> "ExperimentContext":
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        safe_device_name = _safe_filename(device_name)
        experiment_path = (config.output_path / safe_device_name / timestamp)

        logger.info("Creating experiment folders at %s", experiment_path)
        subfolders = ["frida", "no_frida", "mitm", "sslkeys", "logs"]
        try:
            experiment_path.mkdir(parents=True, exist_ok=True)
            for sub in subfolders:
                (experiment_path / sub).mkdir(exist_ok=True)
        except OSError as e:
            logger.exception("Failed to create experiment directories under %s", experiment_path)
            raise RuntimeError(f"Failed to create experiment directories under {experiment_path}: {e}") from e

        context = cls(
            package_name=package_name,
            phone_id=phone_id,
            device_name=device_name,
            experiment_path=experiment_path,
            config=config
        )
        logger.debug(
            "Context created: package=%s phone=%s device=%s",
            package_name, phone_id, device_name
        )
        return context

    def _sleep_times_path(self) -> Path:
        p = getattr(self.config, "sleep_times_path", None)
        return Path(p) if p else None

    @property
    def sleep_times(self) -> SleepTimes:
        if self._sleep_times_manager is None:
            path = self._sleep_times_path()
            logger.debug("Loading SleepTimes from %s", path)
            self._sleep_times_manager = SleepTimes(path)
        return self._sleep_times_manager

    def record_iteration_result(self, phase: str, iteration_index: int, success: bool) -> None:
        """
        Store the outcome of a single iteration.
        phase ∈ {"no_frida", "frida"}
        iteration_index starts at 1.
        """
        self._iteration_results[phase].append((iteration_index, success))

    def summarise_iterations(self) -> str:
        """
        Return a summary like
          no_frida :  8 / 10 (2, 4)
          frida    :  9 / 10 (7)
        where the tuple lists the failed iteration indices; an empty tuple is omitted.
        """
        lines: list[str] = []

        for phase, results in self._iteration_results.items():
            total = len(results)
            failed = [idx for idx, ok in results if not ok]
            success = total - len(failed)

            if failed:
                fail_str = " failed: (" + ", ".join(str(i) for i in failed) + ")"
            else:
                fail_str = ""

            lines.append(f"{phase:10s}: {success:2d} / {total:2d}{fail_str}")

        header = "Experiment summary:"
        summary = header + "\n" + "\n".join(lines)
        out = self.experiment_path / "experiment_summary.txt"

        try:
            out.write_text(summary + "\n", encoding="utf-8")
            logger.info("Wrote iteration summary to %s", out)
        except OSError as e:
            logger.exception("Failed to write iteration summary to %s", out)
            raise RuntimeError(f"Failed to write iteration summary to {out}: {e}") from e
        return summary


from .config import AppConfig
ExperimentContext.model_rebuild()
