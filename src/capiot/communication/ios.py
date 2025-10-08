from __future__ import annotations
from pathlib import Path
from ..context import ExperimentContext
from ..utils.check_image_similarity import compare_images
from ..config import load_image_crop_regions, SshConnectionConfig
from ..utils.process_handler import run_local, ProcessHandle
from .ssh import ssh_connect, exec, SshError
import time, logging, shlex
import wda

from typing import Optional, List, Dict, Mapping

_client: Optional[wda.USBClient] = None
_session: Optional[wda.Session] = None

logger = logging.getLogger(__name__)

def _create_client(udid: str) -> wda.USBClient:
    global _client
    if _client is None:
        logger.info("Creating WDA USBClient for %s", udid)
        _client = wda.USBClient(udid=udid)
    return _client


def _create_session(udid:str, package_name: str) -> wda.Session:
    global _session
    client = _create_client(udid)
    if _session is None:
        logger.debug("Creating WDA session for %s", package_name)
        _session = client.session(package_name)
    return _session


def _close_session() -> None:
    global _session
    if _session is not None:
        try:
            _session.close()
        except Exception as e:
            logger.debug("WDA session close ignored: %s", e)
        _session = None

# ---------------------------------------------------------------------------
# App lifecycle helpers
# ---------------------------------------------------------------------------
def start_app (udid: str, package_name: str):
    try:
        _create_session(udid, package_name)
    except Exception as e:
        logger.error("Failed to start/apply WDA session for %s on %s: %s", package_name, udid, e)
        raise


def stop_app ():
    _close_session()


def uninstall_app (udid: str, package_name: str):
    cmd = ["ideviceinstaller", "-u", udid, "-U", package_name]
    return run_local(cmd)


# ---------------------------------------------------------------------------
# UI‑driving helpers
# ---------------------------------------------------------------------------

def _parse_tap_line(tap_line: str) -> Optional[tuple[int, int]]:
    s = tap_line.strip()
    if not s or s.startswith("#"):
        return None
    parts = s.split()
    if len(parts) != 3 or parts[0] != "tap":
        raise ValueError(f"Unsupported tap line: {tap_line!r} (expected 'tap X Y')")
    try:
        x = int(parts[1]);
        y = int(parts[2])
    except Exception:
        raise ValueError(f"Tap coordinates must be integers: {tap_line!r}")
    return x, y

def perform_tap(tap: str):
    if _session is None:
        logger.warning("perform_tap called without an active WDA session")
        return
    parsed = _parse_tap_line(tap)
    if parsed is None:
        return
    x_px, y_px = parsed
    scale = max(_session.scale, 2)

    x = int(x_px / scale)
    y = int(y_px / scale)
    logger.debug("WDA click at (x=%d, y=%d) [from pixels %d,%d]", x, y, x_px, y_px)
    _session.click(x, y)


def _resolve_crop_region(crop_list: Optional[List[Dict[str, int]]],
                        tap_index: int,
                    ) -> Optional[Mapping[str, int]]:
    """
    Return the crop dict for the tap_index from a list of regions.
    """
    if not crop_list:
        return None
    idx = tap_index - 1
    if idx < 0 or idx >= len(crop_list):
        return None
    return crop_list[idx]


def take_screenshot(screenshot_path: Path) -> None:
    logging.info(f"Saving screenshot to '{screenshot_path}'")
    _client.screenshot(screenshot_path)

def trigger_taps_on_phone(ctx: ExperimentContext, iteration: int, frida: bool):
    if _session is None:
        logger.error("trigger_taps_on_phone called but WDA session is not established")
        return False

    device_name = ctx.device_name
    coords_path = Path(ctx.config.tap_coordinates_path) / device_name
    coordinates_file = coords_path / f"{device_name}.txt"

    if not coordinates_file.exists():
        logger.error("Could not find coordinates file: %s", coordinates_file)
        raise FileNotFoundError(f"Coordinates file not found: {coordinates_file}")

    success = True

    frida_suffix = "frida" if frida else "no_frida"
    phase_dir = ctx.experiment_path / frida_suffix
    phase_dir.mkdir(parents=True, exist_ok=True)
    crop_config = load_image_crop_regions(ctx.config.image_crop_regions_path, device_name)
    after_tap_sleep = ctx.sleep_times.get("after_tap", 2.0)
    after_similarity_sleep = ctx.sleep_times.get("after_similarity", 9.0)
    screenshot_dir = phase_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)


    with coordinates_file.open("r", encoding="utf‑8") as coordinates:
        for tap_counter, tap in enumerate(coordinates, start=1):
            try:
                perform_tap(tap)
            except ValueError as e:
                logger.warning("Skipping invalid tap line %d: %s", tap_counter, e)
                continue
            time.sleep(after_tap_sleep)

            screenshot_name = f"tap-{tap_counter}_iter-{iteration}_{frida_suffix}.png"
            screenshot_path = screenshot_dir / screenshot_name

            take_screenshot(screenshot_path)

            baseline_path = coords_path / f"baseline_tap-{tap_counter}.png"
            region = _resolve_crop_region(crop_config, tap_counter)

            try:
                score = compare_images(str(baseline_path), str(screenshot_path), region)
                logger.info("Image similarity for tap %d: %.5f", tap_counter, score)
                if score < ctx.config.image_similarity_threshold:
                    success = False
            except Exception as e:
                logger.warning("Comparison failed for tap %d: %s", tap_counter, e)
                success = False
            time.sleep(after_similarity_sleep)

    return success

# ---------------------------------------------------------------------------
# Tcpdump
# ---------------------------------------------------------------------------


def start_tcpdump(ssh_config: SshConnectionConfig, interface: str, outfile: Path) -> int:
    """
    Start tcpdump in the background on the phone, returning the PID.
    Uses `doas /usr/bin/tcpdump`.
    """
    iface_q = shlex.quote(interface)
    outfile_q = shlex.quote(str(outfile))

    tcpdump_cmd = f"doas /usr/bin/tcpdump -i {iface_q} -s 0 -U -w {outfile_q} 'not (tcp port 22)'"
    cmd = f"nohup {tcpdump_cmd} </dev/null >/dev/null 2>&1 & echo $!"

    with ssh_connect(ssh_config) as ssh:
        rc, out, err = exec(ssh, cmd)
        if rc != 0:
            raise SshError(f"Failed to start tcpdump: rc={rc} err={err.strip()}")
        try:
            pid = int(out.strip())
            return pid
        except ValueError as ve:
            raise SshError(f"Unexpected PID output from remote tcpdump: {out!r}") from ve
        logger.info("Tcpdump on phone started on %s (PID %d, iface=%s, out=%s)", ssh_config.host, pid, interface, outfile)


def stop_tcpdump(ssh_config: SshConnectionConfig, pid: int) -> None:
    cmd = f"doas /bin/kill -2 {pid} || true"
    with ssh_connect(ssh_config) as ssh:
        exec(ssh, cmd)
    logging.info(f"Remote tcpdump (PID %d) stopped", pid)
