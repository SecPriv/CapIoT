from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which
from typing import List
from ..communication.android import get_apk_paths, pull_file_to_server
from ..actions.user_interaction import print_status_msg

from ..utils.process_handler import run_and_wait


class AndroidDumpError(RuntimeError):
    pass

def _run(cmd: List[str], *, timeout: int = 60 * 5) -> str:
    cp = run_and_wait(cmd, timeout=timeout, check=True)
    return (cp.stdout or "").strip()


def _extract_permissions(apk_path: Path, out_file: Path) -> None:
    """
    Try apkanalyzer → fallback to aapt → save to out_file.
    """
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if which("apkanalyzer"):
        try:
            txt = _run(["apkanalyzer", "manifest", "permissions", str(apk_path)])
            out_file.write_text(txt + "\n", encoding="utf-8")
            print_status_msg(f"Permissions (apkanalyzer) -> {out_file}")
            return
        except Exception as e:
            print_status_msg(f"apkanalyzer failed: {e}; falling back to aapt")

    if which("aapt"):
        try:
            txt = _run(["aapt", "dump", "permissions", str(apk_path)])
            out_file.write_text(txt + "\n", encoding="utf-8")
            print_status_msg(f"Permissions (aapt) -> {out_file}")
            return
        except Exception as e:
            print_status_msg(f"aapt failed: {e}")

    print_status_msg("No permissions tool available (apkanalyzer/aapt). Skipping permissions extraction.")


def dump_android_apks(
    package_name: str,
    phone_id: str,
    base_dir: Path
) -> Path:
    """
    Pull all APK splits for package_name from the Android device into base_dir/<package_name>/.
    Extracts permissions from the base APK (or the first APK found).
    Returns the APK directory path.
    """
    if which("adb") is None:
        raise AndroidDumpError("adb not found in PATH")
    apk_dir = base_dir / package_name
    apk_dir.mkdir(parents=True, exist_ok=True)

    print_status_msg(f"Querying APK paths for {package_name}")
    try:
        paths = get_apk_paths(phone_id, package_name)
    except subprocess.CalledProcessError as e:
        raise AndroidDumpError("adb failed while querying package paths (device offline or unauthorized?)") from e
    except RuntimeError as e:
        raise AndroidDumpError(f"No APKs found for '{package_name}' (is the app installed?)") from e

    print_status_msg(f"Pulling {len(paths)} APK file(s) to {apk_dir}")
    for p in paths:
        try:
            pull_file_to_server(phone_id, p, apk_dir)
        except subprocess.CalledProcessError as e:
            raise AndroidDumpError(f"Failed to pull '{p}' from device") from e


    base_apk = apk_dir / "base.apk"
    if not base_apk.exists():
        apks = sorted([f for f in apk_dir.glob("*.apk")], key=lambda x: x.name)
        if not apks:
            raise AndroidDumpError("No APKs pulled; cannot extract permissions")
        base_apk = apks[0]
    try:
        _extract_permissions(base_apk, apk_dir / "permissions.txt")
    except Exception as e:
        print_status_msg(f"Permissions extraction failed: {e}")

    return apk_dir
