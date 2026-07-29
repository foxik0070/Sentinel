"""
Deterministic command guardrails for AI-proposed actions.

classify(command) returns (risk_score, reasons) where:
  risk_score: 0 (safe) .. 100 (catastrophic)
  reasons:    list[str] explaining each rule that fired

This module is intentionally side-effect-free and has no project imports
so it can be tested standalone and embedded into any execution path.

Scoring is additive and capped at 100. Even a single CRITICAL rule lifts
the score above the "block real execution" threshold; in the current
dry-run-only phase the score is informational and the action is always
forced to mode='dry_run' upstream.
"""

import re
import shlex

THRESHOLD_BLOCK = 70   # >=: never auto-execute, even after human approve
THRESHOLD_REVIEW = 30  # >=: highlight in UI for extra scrutiny

# (severity, compiled_regex, human_readable_reason)
# Severities: CRITICAL=80, HIGH=50, MEDIUM=25, LOW=10
_CRITICAL = 80
_HIGH = 50
_MEDIUM = 25
_LOW = 10

_RULES = [
    # --- catastrophic data loss ---
    (_CRITICAL, re.compile(r"\brm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+(/|/\*|\*|~|\$HOME|\.)(\s|$)"),
        "rm -rf against root/home/wildcard"),
    (_CRITICAL, re.compile(r"\b(mkfs|mkfs\.[a-z0-9]+)\b"),
        "filesystem format"),
    (_CRITICAL, re.compile(r"\bdd\b[^|]*\bof=/dev/(sd|nvme|hd|vd|mmcblk)"),
        "dd to raw block device"),
    (_CRITICAL, re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
        "fork bomb"),
    (_CRITICAL, re.compile(r">\s*/dev/(sd|nvme|hd|vd|mmcblk)"),
        "redirect to raw block device"),
    (_CRITICAL, re.compile(r"\bshred\b\s+.*(/dev/|--remove)"),
        "shred on device or removing files"),
    (_CRITICAL, re.compile(r"\bwipefs\b"),
        "wipefs filesystem signatures"),

    # --- privilege / account ---
    (_HIGH, re.compile(r"\bpasswd\b\s+\S+"),
        "password change"),
    (_HIGH, re.compile(r"\buserdel\b|\bdeluser\b"),
        "user deletion"),
    (_HIGH, re.compile(r"\bchown\s+-R\b.*\s/(\s|$)"),
        "recursive chown of root"),
    (_HIGH, re.compile(r"\bchmod\s+-R\s+777\b"),
        "recursive chmod 777"),
    (_HIGH, re.compile(r"\b(visudo|sudoers)\b"),
        "sudoers modification"),

    # --- network / firewall lockout ---
    (_HIGH, re.compile(r"\biptables\s+-F\b|\biptables\s+--flush\b"),
        "iptables flush (firewall lockout risk)"),
    (_HIGH, re.compile(r"\bufw\s+(disable|reset)\b"),
        "ufw disable/reset"),
    (_HIGH, re.compile(r"\bip\s+link\s+set\s+\S+\s+down\b"),
        "bring interface down"),
    (_HIGH, re.compile(r"\bsystemctl\s+(stop|disable|mask)\s+(sshd|ssh)\b"),
        "stop/disable SSH"),

    # --- power / reboot ---
    (_HIGH, re.compile(r"\b(reboot|halt|poweroff|shutdown)\b"),
        "host power state change"),
    (_HIGH, re.compile(r"\binit\s+0\b|\binit\s+6\b"),
        "init runlevel halt/reboot"),

    # --- remote code execution patterns ---
    (_CRITICAL, re.compile(r"\bcurl\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b"),
        "curl | sh remote execution"),
    (_CRITICAL, re.compile(r"\bwget\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b"),
        "wget | sh remote execution"),
    (_HIGH, re.compile(r"\beval\b\s*[\"']?\$"),
        "eval of variable content"),

    # --- destructive package / kernel ---
    (_HIGH, re.compile(r"\b(apt(-get)?|yum|dnf)\s+(remove|purge|autoremove)\s+(-y\s+)?(linux-image|kernel|systemd|sshd?)"),
        "removal of critical package"),
    (_MEDIUM, re.compile(r"\b(apt(-get)?|yum|dnf)\s+(install|upgrade|dist-upgrade)\b"),
        "package installation/upgrade"),

    # --- SQL danger (in case command embeds SQL) ---
    (_HIGH, re.compile(r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", re.IGNORECASE),
        "SQL DROP statement"),
    (_HIGH, re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
        "SQL TRUNCATE statement"),

    # --- generic recursive deletion ---
    (_MEDIUM, re.compile(r"\brm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+\S"),
        "recursive/force rm"),

    # --- writes to sensitive paths via redirection ---
    (_HIGH, re.compile(r">\s*/etc/(passwd|shadow|sudoers|fstab|hosts)\b"),
        "redirect into critical /etc file"),
    (_MEDIUM, re.compile(r">\s*/(etc|boot|sys|proc)/"),
        "redirect into system path"),

    # --- shell heredoc/chaining hides intent ---
    (_LOW, re.compile(r"(?:^|\s)(&&|\|\||;)\s*\S"),
        "chained commands"),
    (_LOW, re.compile(r"\$\(|\`"),
        "command substitution"),
]

# Allowlist of read-only diagnostic binaries. If the *entire* command is one
# of these (or a pipe-chain made only of these), the score is clamped to 0.
_READONLY_BINS = {
    "ls", "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep",
    "awk", "sed", "cut", "sort", "uniq", "wc", "tr", "find", "stat", "file",
    "ps", "top", "htop", "free", "df", "du", "uptime", "uname", "hostname",
    "id", "who", "w", "last", "lastlog",
    "ss", "netstat", "ip", "route", "ping", "traceroute", "dig", "host", "nslookup",
    "systemctl", "journalctl", "dmesg", "loginctl", "machinectl",
    "lsblk", "lscpu", "lsmem", "lsmod", "lspci", "lsusb", "lsof",
    "date", "echo", "printf", "true", "false", "yes",
    "ipmitool", "smartctl", "sensors",
}

# systemctl/journalctl subcommands that are read-only
_READONLY_SUBCOMMANDS = {
    "systemctl": {"status", "is-active", "is-enabled", "is-failed",
                  "list-units", "list-unit-files", "show", "cat"},
    "journalctl": None,  # journalctl is always read-only in practice
    "ip": {"addr", "a", "route", "r", "link", "neigh", "n", "rule"},
    "ss": None,
}


def _strip_sudo(tokens):
    """Drop leading sudo/env-prefixes so we can inspect the real command."""
    out = list(tokens)
    while out and out[0] in {"sudo", "doas"}:
        out.pop(0)
        # sudo -u user, sudo -E etc.
        while out and out[0].startswith("-"):
            out.pop(0)
    return out


def _is_readonly_invocation(tokens):
    """True iff a single argv looks like a read-only diagnostic call."""
    tokens = _strip_sudo(tokens)
    if not tokens:
        return False
    bin_name = tokens[0].rsplit("/", 1)[-1]
    if bin_name not in _READONLY_BINS:
        return False
    sub_allow = _READONLY_SUBCOMMANDS.get(bin_name, "any")
    if sub_allow == "any" or sub_allow is None:
        return True
    # systemctl/ip: check the first non-flag token
    for t in tokens[1:]:
        if t.startswith("-"):
            continue
        return t in sub_allow
    # No subcommand given — bare invocation is read-only enough (e.g. `ss`)
    return True


def _looks_readonly(command):
    """True iff the whole command line is a pipe-chain of read-only calls
    with no redirections or substitutions."""
    if not command or not isinstance(command, str):
        return False
    if any(ch in command for ch in (">", "<", "`")):
        return False
    if "$(" in command:
        return False
    # Split on pipes; each segment must be a read-only invocation
    segments = [s.strip() for s in command.split("|")]
    if not segments:
        return False
    for seg in segments:
        try:
            tokens = shlex.split(seg)
        except ValueError:
            return False
        if not _is_readonly_invocation(tokens):
            return False
    return True


def classify(command):
    """Score a command for execution risk.

    Returns (risk_score:int, reasons:list[str]).
    risk_score is clamped to [0, 100].
    """
    if not command or not isinstance(command, str):
        return 100, ["empty or non-string command"]

    cmd = command.strip()
    if not cmd:
        return 100, ["empty command"]

    if _looks_readonly(cmd):
        return 0, []

    score = 0
    reasons = []
    for severity, rx, reason in _RULES:
        if rx.search(cmd):
            score += severity
            reasons.append(reason)

    if score > 100:
        score = 100
    return score, reasons


def is_blocked(command):
    """Convenience: True if command must never auto-execute."""
    score, _ = classify(command)
    return score >= THRESHOLD_BLOCK


# Mapping: (regex, builder, description)
# builder(match) -> str  (the read-only preview command)
_SIM_RULES = [
    (re.compile(r"\bsystemctl\s+(?:start|restart|reload|try-restart|stop|disable|enable|mask|unmask)\s+(\S+)"),
        lambda m: f"systemctl status {m.group(1)}; journalctl -u {m.group(1)} -n 50 --no-pager",
        "Service control → show unit status + last 50 journal lines"),

    (re.compile(r"\bkill(?:all)?\b[^|;&]*?\s(-\d+|-[A-Z]+)?\s*(\d+|\S+)\s*$"),
        lambda m: f"ps -p {m.group(2)} -o pid,user,etime,cmd 2>/dev/null || pgrep -af {m.group(2)}",
        "Process kill → show target process details"),

    (re.compile(r"\biptables\s+-(?:A|I|D|R)\s+(\S+)"),
        lambda m: f"iptables -L {m.group(1)} -n --line-numbers",
        "iptables write → list current rules in chain"),
    (re.compile(r"\biptables\s+-F\b|\biptables\s+--flush\b"),
        lambda m: "iptables -L -n --line-numbers",
        "iptables flush → list current rules"),

    (re.compile(r"\bufw\s+(?:enable|disable|reset|allow|deny|reject|delete)\b"),
        lambda m: "ufw status verbose",
        "ufw write → show current status"),

    (re.compile(r"\b(?:rm|unlink)\s+(?:-[a-zA-Z]+\s+)*(\S.*)$"),
        lambda m: f"ls -la {m.group(1)} 2>/dev/null | head -n 20; file {m.group(1)} 2>/dev/null | head -n 20",
        "File deletion → list target(s) + identify file type"),

    (re.compile(r"\bmount\s+(\S+)\s+(\S+)"),
        lambda m: f"findmnt {m.group(2)} 2>/dev/null; lsblk -f {m.group(1)} 2>/dev/null",
        "Mount → inspect current mount + device fs info"),
    (re.compile(r"\bumount\s+(\S+)"),
        lambda m: f"findmnt {m.group(1)} 2>/dev/null; lsof +D {m.group(1)} 2>/dev/null | head -n 20",
        "Umount → show mount + open file handles on it"),

    (re.compile(r"\b(?:reboot|halt|poweroff|shutdown)\b"),
        lambda m: "uptime; who; runlevel; systemctl list-units --state=failed --no-pager",
        "Power state change → show uptime, sessions, failed units"),

    (re.compile(r"\b(?:apt(?:-get)?|yum|dnf)\s+(?:install|upgrade|dist-upgrade|remove|purge|autoremove)\s+(?:-y\s+)?(\S+)"),
        lambda m: f"dpkg -l {m.group(1)} 2>/dev/null || rpm -qi {m.group(1)} 2>/dev/null",
        "Package change → show current package metadata"),

    (re.compile(r"\b(?:passwd|chpasswd)\b\s+(\S+)"),
        lambda m: f"id {m.group(1)} 2>/dev/null; passwd -S {m.group(1)} 2>/dev/null",
        "Password change → show account status"),
    (re.compile(r"\b(?:userdel|deluser)\b\s+(\S+)"),
        lambda m: f"id {m.group(1)} 2>/dev/null; last -n 5 {m.group(1)} 2>/dev/null",
        "User deletion → show id + last logins"),

    (re.compile(r"\bip\s+link\s+set\s+(\S+)\s+(?:up|down)\b"),
        lambda m: f"ip -d link show {m.group(1)}; ip -s link show {m.group(1)}",
        "Interface state change → show link details + counters"),
]


def simulate(command):
    """Return (preview_command:str|None, description:str) for a write-mode command.

    preview_command is a string the operator can run to inspect *current* state
    that the proposed command would change. Returns (None, description) if no
    safe preview can be inferred.
    """
    if not command or not isinstance(command, str):
        return None, "empty or non-string command — nothing to simulate"
    cmd = command.strip()
    if not cmd:
        return None, "empty command"
    if _looks_readonly(cmd):
        return cmd, "command is already read-only — would run as-is"
    for rx, build, desc in _SIM_RULES:
        m = rx.search(cmd)
        if m:
            try:
                preview = build(m)
            except Exception:
                continue
            return preview, desc
    return None, "no deterministic read-only preview available for this command"
