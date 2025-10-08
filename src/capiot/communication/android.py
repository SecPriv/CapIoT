from __future__ import annotations
from pathlib import Path
from subprocess import Popen
from typing import Sequence
import logging, subprocess
import time
import shlex
from typing import Mapping, Optional, List, Dict

from ..utils.process_handler import run_and_wait
from ..context import ExperimentContext
from ..utils.check_image_similarity import compare_images
from ..config import load_image_crop_regions


logger = logging.getLogger("capiot.android")

def _adb(phone_id: str, *adb_args: str, timeout: int | None = 2 * 60) -> str:
    """
    Run an adb command and return stdout. Raises on failure.
    """
    args: Sequence[str] = ("adb", "-s", phone_id, *adb_args)
    logger.debug("ADB: %s", " ".join(shlex.quote(a) for a in args))
    adb_process = run_and_wait(args, timeout=timeout)
    out = (adb_process.stdout or "").strip()
    if out:
        logger.debug("ADB stdout (%d chars)", len(out))
    return out


def _ensure_pcap_name(name: str) -> str:
    """
    Ensure the dump name has `.pcap` extension.
    """
    return name if name.endswith(".pcap") else f"{name}.pcap"

# ---------------------------------------------------------------------------
# App lifecycle helpers
# ---------------------------------------------------------------------------
def start_app(phone_id: str, package_name: str) -> None:
    """
    Launch the app.
    """
    _adb(
        phone_id,
        "shell", "monkey",
        "-p", package_name,
        "-c", "android.intent.category.LAUNCHER",
        "1",
    )


def stop_app(phone_id: str, package_name: str) -> None:
    """
    Stop the app.
    """
    _adb(phone_id, "shell", "am", "force-stop", package_name)


def uninstall_app(phone_id: str, package_name: str) -> None:
    """
    Uninstall app.
    """
    _adb(phone_id, "uninstall", package_name)


def reboot(phone_id: str) -> None:
    """
    Reboot phone
    """
    _adb(phone_id, "reboot")


# ---------------------------------------------------------------------------
# PCAPdroid helpers
# ---------------------------------------------------------------------------
def start_pcapdroid(
    phone_id: str,
    package_name: str,
    dump_name: str,
    phone_interface: str,
    pcapdroid_api_key: str
) -> None:
    """
    Start PCAPdroid remote capture
    """
    out_name = _ensure_pcap_name(dump_name)
    _adb(
        phone_id,
        "shell", "am", "start",
        "-e", "action", "start",
        "-e", "pcap_dump_mode", "pcap_file",
        "-e", "app_filter", package_name,
        "-e", "pcap_name", f"{out_name}",
        "-e", "root_capture", "true",
        "-e", "capture_interface", phone_interface,
        "-e", "auto_block_private_dns", "false",
        "-e", "api_key", pcapdroid_api_key,
        "-n", "com.emanuelef.remote_capture/com.emanuelef.remote_capture.activities.CaptureCtrl",
    )


def stop_pcapdroid(phone_id: str, pcapdroid_api_key: str) -> None:
    """
    Stop the PCAPdroid remote capture.
    """
    _adb(
        phone_id,
        "shell", "am", "start",
        "-e", "action", "stop",
        "-e", "api_key", pcapdroid_api_key,
        "-n", "com.emanuelef.remote_capture/com.emanuelef.remote_capture.activities.CaptureCtrl",
    )

# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------
def pull_file_to_server(
    phone_id: str,
    file_path: Path,
    destination_path: Path,
) -> None:
    """
    Pull file from the phone to the server.
    """
    logger.info("Pulling %s -> %s", file_path, destination_path)
    _adb(phone_id, "pull", str(file_path), str(destination_path))


def delete_file_from_phone(
    phone_id: str,
    file_path: Path,
) -> None:
    """
    Remove a file on the phone.
    """
    logger.debug("Deleting phone file %s", file_path)
    _adb(phone_id, "shell", "su", "-c", "rm", str(file_path))


# ---------------------------------------------------------------------------
# Bluetooth helpers
# ---------------------------------------------------------------------------
def enable_bluetooth(phone_id: str) -> None:
    logger.info("Enabling Bluetooth")
    _adb(phone_id, "shell", "svc", "bluetooth", "enable")

def disable_bluetooth(phone_id: str) -> None:
    logger.info("Disabling Bluetooth")
    _adb(phone_id, "shell", "svc", "bluetooth", "disable")


def pull_bluetooth_log_to_server(phone_id: str, device_name: str, experiment_path: Path, bluetooth_log_path: Path) -> None:
    """
    Copy Bluetooth log to an accessible SDCard path, pull it to the experiment folder,
    then remove the phone-side copy.
    """
    if not bluetooth_log_path:
        logger.warning("bluetooth_log_path is not set in config; skipping Bluetooth log pull.")
        return None

    bluetooth_log_file = f"bluetooth-{device_name}.log"
    dest_path = experiment_path / bluetooth_log_file
    sdcard_dir = "/sdcard/Download"
    accessible_path = f"{sdcard_dir}/{bluetooth_log_file}"

    try:
        logger.info("Staging Bluetooth log on device: %s -> %s", bluetooth_log_path, accessible_path)
        _adb(
            phone_id,
            "shell",
            "su", "-c",
            f"cp {bluetooth_log_path} {accessible_path} && chmod 666 {accessible_path}",
        )
        logger.info("Pulling staged Bluetooth log to %s", dest_path)
        _adb(
            phone_id,
            "pull",
            accessible_path,
            str(dest_path),
        )
        logger.info("Bluetooth log pulled to %s", dest_path)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to copy/pull Bluetooth log: %s", e)
        return
    finally:
        try:
            delete_file_from_phone(phone_id, accessible_path)
        except Exception as exc:
            logger.warning("Could not delete staged Bluetooth log on phone: %s", exc)


# ---------------------------------------------------------------------------
# UI‑driving helpers
# ---------------------------------------------------------------------------
def disable_autorotate(phone_id: str) -> None:
    logger.debug("Disabling autorotate")
    _adb(phone_id, "shell", "settings", "put", "system", "accelerometer_rotation", "0")

def perform_tap(phone_id: str, tap: str) -> None:
    line = tap.strip()
    if not line or line.startswith("#"):
        return
    parts = line.split()
    if len(parts) != 3 or parts[0] != "tap":
        raise ValueError(f"Unsupported tap line: {tap!r} (expected 'tap X Y')")
    _, x, y = parts
    logger.debug("Performing tap at %s,%s", x, y)
    _adb(phone_id, "shell", "input", tap)

def take_screenshot(phone_id: str, dest_path: Path) -> None:
    """
    Capture a PNG screenshot from the device and write it to *dest_path*.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("Taking screenshot -> %s", dest_path)
    try:
        with dest_path.open("wb") as screenshot_img:
            subprocess.run(
                ["adb", "-s", phone_id, "exec-out", "screencap", "-p"],
                check=True,
                stdout=screenshot_img,
            )
    except subprocess.CalledProcessError as e:
        logger.error("Failed to take screenshot: %s", e)
        raise

def _resolve_crop_region(
                        crop_list: Optional[List[Dict[str, int]]],
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

def trigger_taps_on_phone(ctx: ExperimentContext, iteration: int, frida: bool) -> bool:
    """
    Execute taps from the coordinates file, take screenshots into the experiment
    folder, and compare with baselines. Returns True if all comparisons meet the
    similarity threshold.
    """
    device_name = ctx.device_name
    coords_path = Path(ctx.config.tap_coordinates_path) / f"{device_name}"
    coordinates_file = coords_path / f"{device_name}.txt"

    if not coordinates_file.exists():
        logger.error("Could not find coordinates file: %s", coordinates_file)
        raise FileNotFoundError(f"Coordinates file not found: {coordinates_file}")

    disable_autorotate(ctx.phone_id)

    success = True

    frida_suffix = "frida" if frida else "no_frida"
    phase_dir = ctx.experiment_path / frida_suffix
    phase_dir.mkdir(parents=True, exist_ok=True)
    crop_config = load_image_crop_regions(ctx.config.image_crop_regions_path, device_name)
    after_tap_sleep = ctx.sleep_times.get("after_tap", 2.0)
    after_similarity_sleep = ctx.sleep_times.get("after_similarity", 9.0)

    screenshots_dir = phase_dir / "screenshots"
    phase_dir.mkdir(parents=True, exist_ok=True)

    with coordinates_file.open("r", encoding="utf‑8") as coordinates:
        for tap_counter, tap in enumerate(coordinates, start=1):
            try:
                perform_tap(ctx.phone_id, tap)
            except ValueError as e:
                logger.warning("Skipping invalid tap line %d: %s", tap_counter, e)
                continue
            time.sleep(after_tap_sleep)


            screenshot_name = f"tap-{tap_counter}_iter-{iteration}_{frida_suffix}.png"
            screenshot_path = screenshots_dir / screenshot_name

            take_screenshot(phone_id=ctx.phone_id, dest_path=screenshot_path)

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

def capture_taps_live(phone_id: str) -> Popen[str]:
    logger.info("Starting live tap capture on %s", phone_id)
    return subprocess.Popen(
        ["adb", "-s", phone_id, "shell", "getevent", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )




# ---------------------------------------------------------------------------
# Dump APK Helpers
# ---------------------------------------------------------------------------
def get_apk_paths(device_id: str, package_name: str) -> List[str]:
    out = _adb(device_id, "shell", "pm", "path", package_name)
    paths = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            paths.append(line.split(":", 1)[1])
    if not paths:
        logger.error("No package found")
        raise RuntimeError(f"No APK paths found for {package_name}")
    return paths