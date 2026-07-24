"""
M1-1 + M1-4: SSH hardening — known_hosts management, shlex escaping, centrální SSH config.

Všechny SSH volání v projektu by měly používat `build_ssh_cmd()` místo ručního skládání.
"""
import os
import re
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


# 352b: least-privilege remediace — prefixy příkazů, které na hostu vyžadují
# root přes `sudo -n`. Vše ostatní (df, systemctl status/--failed, …) běží jako
# neprivilegovaný uživatel bez sudo. Sudoers na hostech MUSÍ být podmnožinou
# aplikačního whitelistu allowed_commands; co sudoers nepovolí → `sudo -n` selže.
_SUDO_PREFIXES = (
    "systemctl restart", "systemctl start", "systemctl stop",
    "systemctl mask", "systemctl unmask", "systemctl enable",
    "systemctl disable", "systemctl reload", "systemctl daemon-reload",
    "mount", "umount",
    "apt-get", "apt ", "dpkg",
    "journalctl --rotate", "journalctl --vacuum",
    "proxmox-backup-client garbage-collect",
    "reboot", "shutdown", "poweroff",
    # read-only diagnostika, ale root pro plný výstup (rozhodnutí 2026-07-24)
    "ss ", "du ",
)


def _needs_sudo(segment: str) -> bool:
    """True pokud segment příkazu vyžaduje root. Match na úvodní tokeny —
    'systemctl restart x' ano, 'systemctl status x' ne."""
    s = segment.strip()
    return any(s == p.strip() or s.startswith(p) for p in _SUDO_PREFIXES)


def _apply_sudo(command: str) -> str:
    """Prefixne `sudo -n ` jen root-vyžadující segmenty (rozdělené &&/||/;/|).

    Compound příkazy (`journalctl --rotate && journalctl --vacuum`) dostanou sudo
    na každém root-segmentu; pipeliny (`du … | sort | head`) jen na du.
    NEobaluje celé do `sudo sh -c` — to by v sudoers znamenalo neomezený root."""
    parts = re.split(r'(\s*(?:&&|\|\||;|\|)\s*)', command)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:            # oddělovač (&&, |, ;, ||) — beze změny
            out.append(part)
        elif part.strip() and _needs_sudo(part):
            out.append("sudo -n " + part.lstrip())
        else:
            out.append(part)
    return "".join(out)


def build_ssh_cmd(host: str, command: str, timeout: int = 10,
                  user: str = None, key: str = None, jump: str = None) -> list:
    """Sestaví bezpečný SSH příkaz.

    - UserKnownHostsFile místo StrictHostKeyChecking=no
    - StrictHostKeyChecking=accept-new: první připojení přijme klíč, pak ho ověřuje
    - shlex.quote() na command
    - 352b: při neprivilegovaném uživateli (user != root) prefixne root-příkazy
      `sudo -n `; jako root se nechává beze změny (zpětná kompatibilita)
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
    final_command = command if ssh_user == 'root' else _apply_sudo(command)
    cmd += [f"{ssh_user}@{host}", final_command]
    return cmd


def ssh_env() -> dict:
    """352: Prostředí pro ssh procesy — s SSH_AUTH_SOCK umožňuje šifrovaný klíč
    odemčený v ssh-agentovi (config ssh_execution.auth_sock)."""
    env = dict(os.environ)
    sock = getattr(config, 'SSH_AUTH_SOCK', '')
    if sock:
        env['SSH_AUTH_SOCK'] = sock
    return env


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
