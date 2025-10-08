from __future__ import annotations

import os, shutil, zipfile, shlex
from pathlib import Path
from typing import Optional, List

import paramiko
from scp import SCPClient

from ..config import SshConnectionConfig
from ..communication.ssh import ssh_connect, exec, SshError
from ..actions.user_interaction import print_status_msg

class IOSDumpError(RuntimeError):
    pass


def _find_app_dirs(ssh: paramiko.SSHClient, bundle_id: str) -> List[str]:
    # Search application containers
    cmd1 = (
        r"sh -c 'grep -inl --include=Info.plist "
        + shlex.quote(bundle_id)
        + r" /private/var/containers/Bundle/Application/*/*/*.plist || true'"
    )
    _, out1, _ = exec(ssh, cmd1)
    matches = [os.path.dirname(p.strip()) for p in out1.splitlines() if p.strip()]
    if matches:
        return matches
    # Fallback to system apps
    cmd2 = (
        r"sh -c 'grep -inl --include=Info.plist "
        + shlex.quote(bundle_id)
        + r" /Applications/*/*.plist || true'"
    )
    _, out2, _ = exec(ssh, cmd2)
    return [os.path.dirname(p.strip()) for p in out2.splitlines() if p.strip()]


def _scp_dir(ssh: paramiko.SSHClient, remote_dir: str, local_payload_dir: Path, timeout: int = 1200) -> None:
    local_payload_dir.mkdir(parents=True, exist_ok=True)
    with SCPClient(ssh.get_transport(), socket_timeout=timeout) as scp:
        print_status_msg(f"SCP get {remote_dir} -> {local_payload_dir} (recursive)")
        scp.get(remote_path=remote_dir, local_path=str(local_payload_dir), recursive=True)


def _make_reproducible_zip(payload_dir: Path, ipa_path: Path) -> None:
    # Normalize mtimes for reproducible hashes
    for f in payload_dir.rglob("*"):
        try:
            os.utime(f, (0, 0))
        except Exception:
            pass

    ipa_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ipa_path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
        for root, _, files in os.walk(payload_dir):
            files.sort()
            for name in files:
                fp = Path(root) / name
                rel = fp.relative_to(payload_dir.parent)
                zi = zipfile.ZipInfo(str(rel))
                zi.date_time = (1980, 1, 1, 0, 0, 0)
                zi.external_attr = 0o644
                with open(fp, "rb") as src:
                    z.writestr(zi, src.read())


def _extract_permission(permissions_dir: Path, extracted_dir: Path, ipa_path: Path, bundle_id: str) -> None:
    permissions_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ipa_path, "r") as z:
        z.extractall(extracted_dir)
    found_plist = next((p for p in (extracted_dir / "Payload").rglob("Info.plist")), None)
    if found_plist:
        dst = permissions_dir / f"{bundle_id}_Info.plist"
        shutil.copy(found_plist, dst)
        print_status_msg(f"Info.plist extracted to: {dst}")
    else:
        print_status_msg("Info.plist not found in extracted IPA")

def dump_ios_ipa(
    bundle_id: str,
    ssh_config: SshConnectionConfig,
    output_dir: Path,
    udid: str
) -> Path:
    """
    Dump a decrypted .app and package as IPA.

    Steps:
      - SSH: find .app dir by matching Info.plist with bundle id
      - SCP the .app into <output_dir>/Payload/
      - Create <bundle_id>_dump.ipa
      - Extract Info.plist into <output_dir>/permissions/<bundle_id>_Info.plist
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    payload_dir = output_dir / "Payload"
    extracted_dir = output_dir / "extracted"
    permissions_dir = output_dir / "permissions"
    ipa_path = output_dir / f"{bundle_id}_dump.ipa"

    ssh: Optional[paramiko.SSHClient] = None
    try:
        try:
            ssh = ssh_connect(ssh_config)
        except SshError as e:
            raise IOSDumpError(str(e)) from e

        matches = _find_app_dirs(ssh, bundle_id)
        if not matches:
            raise IOSDumpError(f"App {bundle_id} not found on device.")
        app_dir = next((m for m in matches if m.lower().endswith(".app")), None)
        if not app_dir:
            raise IOSDumpError(f"No .app directory found for {bundle_id} (matches: {matches})")

        _scp_dir(ssh, app_dir, payload_dir)
        _make_reproducible_zip(payload_dir, ipa_path)
        _extract_permission(permissions_dir, extracted_dir, ipa_path, bundle_id)

        return ipa_path

    except Exception as e:
        raise IOSDumpError(str(e)) from e
    finally:
        for d in (payload_dir, extracted_dir):
            try:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
        try:
            if ssh:
                ssh.close()
        except Exception:
            pass
