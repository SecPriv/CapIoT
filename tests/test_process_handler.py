from __future__ import annotations

import os
import shlex
import sys
import time
from pathlib import Path
import subprocess

import pytest

import capiot.utils.process_handler as process_handler


LINUX_ONLY = pytest.mark.skipif(sys.platform.startswith("win"), reason="Linux-only tests")


def test_format_cmd_quotes_correctly():
    args = ["echo", "a b", "c'd", 'e"f', "$HOME", "🙃"]
    expected = " ".join(shlex.quote(a) for a in args)
    assert process_handler._format_cmd(args) == expected


def test_merge_env_merges_without_mutating_os_environ(monkeypatch):
    monkeypatch.setenv("KEEP", "1")
    custom = {"FOO": "bar", "KEEP": "2"}
    merged = process_handler._merge_env(custom)
    assert merged["FOO"] == "bar"
    assert merged["KEEP"] == "2"
    assert "KEEP" in os.environ and os.environ["KEEP"] == "1"
    assert merged is not os.environ


def _is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _wait_until(path: Path, timeout: float = 3.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


# Small Python snippet that spawns a child and sleeps.
SPAWNER_CODE = r"""
import os, sys, time, subprocess
ppath, cpath = sys.argv[1], sys.argv[2]
with open(ppath, "w") as f:
    f.write(str(os.getpid()))
    f.flush()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(cpath, "w") as f:
    f.write(str(child.pid))
    f.flush()
time.sleep(60)
"""


@LINUX_ONLY
def test_run_local_basic_and_kill(tmp_path: Path):
    handle = process_handler.run_local([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert handle.is_running()
        assert _is_pid_running(handle.pid)

        # Force kill the process group
        handle.kill_tree()
        # Should exit quickly
        rc = handle.wait(timeout=3)
        assert rc != 0
        assert not handle.is_running()
        assert not _is_pid_running(handle.pid)
    finally:
        try:
            handle.kill_tree()
        except Exception:
            pass


@LINUX_ONLY
def test_run_local_kill_tree_kills_children(tmp_path: Path):
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"

    handle = process_handler.run_local([sys.executable, "-c", SPAWNER_CODE, str(parent_pid_file), str(child_pid_file)])
    try:
        assert _wait_until(parent_pid_file, 3.0)
        assert _wait_until(child_pid_file, 3.0)

        parent_pid = int(parent_pid_file.read_text())
        child_pid = int(child_pid_file.read_text())

        assert handle.pid == parent_pid
        assert _is_pid_running(parent_pid)
        assert _is_pid_running(child_pid)

        handle.kill_tree()
        handle.wait(timeout=3)

        assert not _is_pid_running(parent_pid)
        assert not _is_pid_running(child_pid)
    finally:
        try:
            handle.kill_tree()
        except Exception:
            pass



@LINUX_ONLY
def test_run_and_wait_success_captures_output():
    cp = process_handler.run_and_wait([sys.executable, "-c", 'print("ok"); import sys; print("err", file=sys.stderr)'], check=True)
    assert cp.returncode == 0
    assert cp.stdout.strip().splitlines()[0] == "ok"
    assert "err" in cp.stderr


@LINUX_ONLY
def test_run_and_wait_nonzero_raises_with_captured_streams():
    with pytest.raises(subprocess.CalledProcessError) as ei:
        process_handler.run_and_wait([sys.executable, "-c", 'import sys; print("out"); print("err", file=sys.stderr); sys.exit(3)'], check=True)
    e = ei.value
    assert e.returncode == 3
    assert "out" in (e.output or "")
    assert "err" in (e.stderr or "")


@LINUX_ONLY
def test_run_and_wait_nonzero_no_check_returns_completed():
    cp = process_handler.run_and_wait([sys.executable, "-c", "import sys; sys.exit(5)"], check=False)
    assert cp.returncode == 5
    assert isinstance(cp.stdout, str) and isinstance(cp.stderr, str)


@LINUX_ONLY
def test_run_and_wait_timeout_kills_group_and_raises(tmp_path: Path):
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"

    args = [sys.executable, "-c", SPAWNER_CODE, str(parent_pid_file), str(child_pid_file)]

    # Give the child time to be spawned and pids written before timeout triggers.
    with pytest.raises(subprocess.TimeoutExpired) as ei:
        process_handler.run_and_wait(args, timeout=1.5, check=False)

    # PIDs should have been written by then; if not, the process died too fast — be explicit
    assert parent_pid_file.exists(), "parent.pid not created before timeout"
    assert child_pid_file.exists(), "child.pid not created before timeout"

    parent_pid = int(parent_pid_file.read_text())
    child_pid = int(child_pid_file.read_text())

    # After timeout handling, both should be gone (SIGTERM then SIGKILL on group)
    # Allow a brief grace period in case OS reaping is slightly delayed.
    t0 = time.time()
    while time.time() - t0 < 2.0 and (_is_pid_running(parent_pid) or _is_pid_running(child_pid)):
        time.sleep(0.05)

    assert not _is_pid_running(parent_pid)
    assert not _is_pid_running(child_pid)
