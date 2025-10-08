from __future__ import annotations
import os, logging
from pathlib import Path
from ..utils.process_handler import run_local, ProcessHandle

logger = logging.getLogger(__name__)

def start_tcpdump(interface: str, outfile: Path) -> ProcessHandle:
    cmd = ["tcpdump", "-i", interface, "-s", "0", "-w", str(outfile)]
    return run_local(cmd)

def start_mitmdump(outfile: Path,  log_folder: Path, port: int = 8080, sslkey_logfile: Path = None) -> ProcessHandle:
    env = os.environ.copy()
    if sslkey_logfile:
        env["SSLKEYLOGFILE"] = str(sslkey_logfile)

    mqtt_script_path = Path(__file__).parent / "mqtt_message.py"
    cmd = [
        "mitmdump",
        "--mode", "transparent",
        "-p", str(port),
        "-w", str(outfile),
        "--tcp-hosts", ".*",
        "--set", 'udp_hosts=.*',
        "--ssl-insecure",
        "-s", str(mqtt_script_path.resolve()),
    ]
    log_folder = Path(log_folder)
    log_folder.mkdir(parents=True, exist_ok=True)
    out_path = log_folder / "mitm.log"
    err_path = log_folder / "mitm.err"
    f_out = out_path.open("ab")
    f_err = err_path.open("ab")
    try:
        return run_local(cmd, env=env, stdout=open(f"{log_folder}/mitm.log", "ab"), stderr=open(f"{log_folder}/mitm.err", "ab"))
    except Exception as e:
        f_out.close()
        f_err.close()
        raise

def start_frida(phone_id: str, package_name: str, log_folder: Path) -> ProcessHandle:
    log_folder = Path(log_folder)
    log_folder.mkdir(parents=True, exist_ok=True)
    out_path = log_folder / "frida.log"
    err_path = log_folder / "frida.err"

    f_out = out_path.open("ab")
    f_err = err_path.open("ab")

    cmd = ["frida", "-D", phone_id, "--codeshare", "akabe1/frida-multiple-unpinning", "-f", package_name]
    try:
        process = run_local(cmd, stdout=f_out, stderr=f_err)
    except Exception:
        f_out.close()
        f_err.close()
        raise

    try:
        process.popen.stdin.write(b"y\n")
        process.popen.stdin.flush()
    except Exception as e:
        logger.debug("Could not write 'y' to frida stdin (may be fine): %s", e)
    return process

def start_objection(phone_id: str, package_name: str, log_folder: Path) -> ProcessHandle:
    log_folder = Path(log_folder)
    log_folder.mkdir(parents=True, exist_ok=True)
    out_path = log_folder / "objection.log"
    err_path = log_folder / "objection.err"

    cmd = [
        "objection",
        "-S", phone_id,
        "-g", package_name,
        "explore",
        "--startup-command", "ios sslpinning disable",
    ]
    f_out = out_path.open("ab")
    f_err = err_path.open("ab")
    try:
        return run_local(cmd, stdout=f_out, stderr=f_err)
    except Exception:
        f_out.close()
        f_err.close()
        raise


def reset_terminal() -> ProcessHandle:
    cmd = ["stty", "sane"]
    return run_local(cmd, stdout=None, stderr=None)
