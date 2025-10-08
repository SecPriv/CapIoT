import logging
from pathlib import Path
import os
from ..utils.process_handler import run_and_wait

logger = logging.getLogger(__name__)

class IptablesError(RuntimeError):
    """Raised when applying iptables rules via script fails."""

def apply_rules(script: Path) -> None:
    path = Path(script).expanduser().resolve()
    if not path.exists() or not path.is_file():
        msg = f"iptables script not found: {path}"
        logger.error(msg)
        raise FileNotFoundError(msg)
    if not os.access(path, os.X_OK):
        msg = f"iptables script not found: {path}"
        logger.error(msg)
        raise IptablesError(msg)
    cmd = ["sudo", "-n", str(path)]
    try:
        run_and_wait(
            cmd,
            timeout=2 * 60,
        )
    except Exception as exc:
        hint = ""
        if hasattr(exc, "stderr"):
            stderr = getattr(exc, "stderr") or ""
            if "a password is required" in stderr or "may not run sudo" in stderr:
                hint = (
                    " (sudo needs a password; run 'sudo -v' beforehand or configure "
                    "NOPASSWD for this command in sudoers)"
                )
        logger.warning("iptables script failed: %s%s", exc, hint)
        raise IptablesError(f"Failed to apply iptables rules with {path}{hint}") from exc


