from __future__ import annotations
import os
import signal
import shlex
import subprocess, logging, time
from typing import Sequence, Mapping, Optional

logger = logging.getLogger("capiot.proc")

def _format_cmd(args: Sequence[str]) -> str:
    return " ".join(shlex.quote(a) for a in args)


def _merge_env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    if env is None:
        return os.environ.copy()
    merged = os.environ.copy()
    merged.update(env)
    return merged

class ProcessHandle:
    def __init__(self, popen: subprocess.Popen):
        self.popen = popen

    @property
    def pid(self) -> int:
        return self.popen.pid

    def is_running(self) -> bool:
        return self.popen.poll() is None

    def wait(self, timeout: Optional[float] = None) -> int:
        return self.popen.wait(timeout=timeout)

    def terminate(self) -> None:
        """Send SIGTERM to the process group (graceful stop)."""
        try:
            os.killpg(os.getpgid(self.popen.pid), signal.SIGTERM)
        except Exception:
            try:
                self.popen.terminate()
            except Exception:
                pass

    def kill_tree(self) -> None:
        """Forcefully kill the process group with SIGKILL."""
        try:
            os.killpg(os.getpgid(self.popen.pid), signal.SIGKILL)
        except Exception:
            try:
                self.popen.kill()
            except Exception:
                pass

def run_local(
    args: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    stdout=None,
    stderr=None,
    stdin=None,
) -> ProcessHandle:
    """
    Spawn a long-running process in its own session so we can kill its children.
    Returns a ProcessHandle; caller is responsible for reading/waiting.
    """
    cmd = _format_cmd(args)
    logger.debug("Spawn: %s (cwd=%s)", cmd, cwd or os.getcwd())
    popen = subprocess.Popen(
        args,
        cwd=cwd,
        env=_merge_env(env),
        stdout=stdout or subprocess.PIPE,
        stderr=stderr or subprocess.PIPE,
        stdin=stdin or subprocess.PIPE,
        start_new_session=True,
    )
    logger.debug("Spawned pid=%d", popen.pid)
    return ProcessHandle(popen)

def run_and_wait(
    args: Sequence[str],
    *,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a command to completion (Linux).
      - Starts in a new session to allow group termination on timeout.
      - Captures stdout/stderr as text.
      - If check=True, raises CalledProcessError on non-zero returncode.
      - On timeout, sends SIGTERM to the group, waits briefly, then SIGKILL,
        and raises TimeoutExpired with any captured output.
    """
    cmd = _format_cmd(args)
    logger.debug("Run: %s (cwd=%s, timeout=%s)", cmd, cwd or os.getcwd(), timeout)
    t0 = time.perf_counter()

    proc = subprocess.Popen(
        args,
        cwd=cwd,
        env=_merge_env(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        logger.error("Timeout (%.1fs) for: %s (pid=%d). Terminating group…", timeout or -1, cmd, proc.pid)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        try:
            stdout, stderr = proc.communicate(timeout=1)
        except Exception:
            stdout, stderr = (e.output, getattr(e, "stderr", None))

        raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
    finally:
        elapsed = time.perf_counter() - t0
        logger.debug("Finished: %s (rc=%s, %.2fs)", cmd, proc.returncode, elapsed)

    if check and proc.returncode:
        logger.debug("Stdout: %s", stdout)
        logger.debug("Stderr: %s", stderr)
        logger.error("Command failed (rc=%d): %s", proc.returncode, cmd)
        raise subprocess.CalledProcessError(proc.returncode, args, output=stdout, stderr=stderr)

    return subprocess.CompletedProcess(args=args, returncode=proc.returncode, stdout=stdout, stderr=stderr)
