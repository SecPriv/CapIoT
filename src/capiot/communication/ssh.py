from sys import path_hooks

import paramiko
from ..config import SshConnectionConfig
import logging, shlex

from typing import Tuple

logger = logging.getLogger("capiot.ssh")


class SshError(RuntimeError):
    """Raised when an SSH action fails."""

def ssh_connect(ssh_config: SshConnectionConfig) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=ssh_config.host,
            port=ssh_config.port,
            username=ssh_config.username,
            password=ssh_config.password or None,
            key_filename=str(ssh_config.key_path) if ssh_config.key_path else None,
            allow_agent=False,
            look_for_keys=False,
            compress=True,
        )
        return client
    except Exception as e:
        raise SshError(f"Failed to connect to {ssh_config.host}: {e}")


def exec(ssh: paramiko.SSHClient, cmd: str) -> Tuple[int, str, str]:
    logger.debug("SSH exec: %s", cmd)
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd)
        chan = stdout.channel
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = chan.recv_exit_status()
        logger.debug("SSH exec rc=%s, out=%dB, err=%dB", rc, len(out), len(err))
        return rc, out, err
    except Exception as e:
        logger.error("SSH exec failed: %s", e)
        raise SshError(f"SSH exec failed: {e}") from e

def start_remote_tcpdump(ssh_config: SshConnectionConfig, interface: str, outfile: str) -> int:
    iface_q = shlex.quote(interface)
    outfile_q = shlex.quote(outfile)

    cmd = (
        f"nohup tcpdump -i {iface_q} -s0 -U -w {outfile_q} "
        f"'not (tcp port 22)' </dev/null >/dev/null 2>&1 & echo $!"
    )
    with ssh_connect(ssh_config) as ssh:
        rc, out, err = exec(ssh, cmd)
        if rc != 0:
            raise SshError(f"Failed to start tcpdump: rc={rc} err={err.strip()}")
        pid_str = out.strip()
        try:
            pid = int(pid_str)
        except ValueError as ve:
            raise SshError(f"Unexpected PID output from remote tcpdump: {pid_str!r}") from ve
        logger.info("Remote tcpdump started on %s (PID %d, iface=%s, out=%s)", ssh_config.host, pid, interface, outfile)
        return pid



def stop_remote_tcpdump(ssh_config: SshConnectionConfig, pid: int) -> None:
    cmd = f"kill -2 {pid} || true"
    with ssh_connect(ssh_config) as ssh:
        exec(ssh, cmd)
    logging.info(f"Remote tcpdump (PID %d) stopped", pid)


def create_folder(ssh_config: SshConnectionConfig, path: str) -> None:
    cmd = f"mkdir -p {path}"
    with ssh_connect(ssh_config) as ssh:
        exec(ssh, cmd)
    logging.debug(f"Remote folder %s created", path)


def download_remote_file(ssh_config: SshConnectionConfig, remote_path: str, local_path: str) -> None:
    with ssh_connect(ssh_config) as ssh:
        sftp = ssh.open_sftp()
        try:
            logger.info("Downloading %s:%s -> %s", ssh_config.host, remote_path, local_path)
            sftp.get(str(remote_path), str(local_path))
            sftp.remove(str(remote_path))
        except Exception as e:
            logger.error("Failed to download remote file: %s", e)
        finally:
            try:
                sftp.close()
            except Exception:
                logger.error("Closing sftp failed: %s", e)
    logger.debug("Downloaded %s:%s → %s", ssh_config.host, remote_path, local_path)