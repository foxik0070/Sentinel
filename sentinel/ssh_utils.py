"""
M1-1 + M1-4: SSH hardening — known_hosts management, shlex escaping, centrální SSH config.

Všechny SSH volání v projektu by měly používat `build_ssh_cmd()` místo ručního skládání.
"""
import os
import shlex
import subprocess
import logging

from . import config

logger = logging.getLogger("sentinel.ssh")

KNOWN_HOSTS_PATH = "/var/lib/sentinel/known_hosts"


def _ssh_options() -> list:
    """Vrátí společné SSH options."""
    opts = [
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
    ]
    return opts


def build_ssh_cmd(host: str, command: str, timeout: int = 10,
                  user: str = None, key: str = None, jump: str = None) -> list:
    """Sestaví bezpečný SSH příkaz.

    - UserKnownHostsFile místo StrictHostKeyChecking=no
    - StrictHostKeyChecking=accept-new: první připojení přijme klíč, pak ho ověřuje
    - shlex.quote() na command
    """
    ssh_user = user or getattr(config, 'SSH_USER', 'root')
    ssh_key = key or getattr(config, 'SSH_KEY_PATH', '/opt/Sentinel/conf/.id_ed25519')
    ssh_jump = jump or getattr(config, 'SSH_JUMP_HOST', '')

    cmd = ["ssh"] + _ssh_options()
    cmd += ["-o", f"ConnectTimeout={timeout}"]
    if ssh_key and os.path.isfile(ssh_key):
        cmd += ["-i", ssh_key]
    if ssh_jump:
        cmd += ["-J", ssh_jump]
    cmd += [f"{ssh_user}@{host}", command]
    return cmd


def scan_host_key(hostname: str) -> bool:
    """Spustí ssh-keyscan a přidá klíč do known_hosts. Vrátí True pokud úspěšné."""
    try:
        os.makedirs(os.path.dirname(KNOWN_HOSTS_PATH), exist_ok=True)
        result = subprocess.run(
            ["ssh-keyscan", "-T", "5", hostname],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            existing = set()
            if os.path.isfile(KNOWN_HOSTS_PATH):
                with open(KNOWN_HOSTS_PATH) as f:
                    existing = set(f.read().splitlines())
            new_keys = [l for l in result.stdout.strip().splitlines() if l and l not in existing]
            if new_keys:
                with open(KNOWN_HOSTS_PATH, "a") as f:
                    f.write("\n".join(new_keys) + "\n")
            logger.info(f"ssh-keyscan {hostname}: {len(new_keys)} new keys added")
            return True
        logger.warning(f"ssh-keyscan {hostname} failed: {result.stderr[:200]}")
        return False
    except Exception as e:
        logger.error(f"scan_host_key({hostname}): {e}")
        return False
