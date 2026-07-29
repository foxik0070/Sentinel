"""352b: least-privilege remediace — sudo prefixing v build_ssh_cmd."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel.ssh_utils import _needs_sudo, _apply_sudo, build_ssh_cmd


class TestNeedsSudo(unittest.TestCase):
    def test_root_commands_need_sudo(self):
        for c in ["systemctl restart nginx.service", "systemctl stop x", "mount -a",
                  "apt-get update", "apt-get upgrade -y", "journalctl --rotate",
                  "journalctl --vacuum-time=7d", "reboot", "ss -tlnp",
                  "du -sh /var/*", "proxmox-backup-client garbage-collect x"]:
            self.assertTrue(_needs_sudo(c), f"{c!r} má vyžadovat sudo")

    def test_diagnostic_commands_no_sudo(self):
        for c in ["df -h", "systemctl status nginx.service",
                  "systemctl --failed --no-pager", "uptime", "free -m"]:
            self.assertFalse(_needs_sudo(c), f"{c!r} nemá vyžadovat sudo")

    def test_systemctl_status_not_confused_with_start(self):
        # prefix 'systemctl start' nesmí matchnout 'systemctl status'
        self.assertFalse(_needs_sudo("systemctl status foo"))
        self.assertTrue(_needs_sudo("systemctl start foo"))


class TestApplySudo(unittest.TestCase):
    def test_simple_root(self):
        self.assertEqual(_apply_sudo("systemctl restart x"), "sudo -n systemctl restart x")

    def test_simple_diagnostic_unchanged(self):
        self.assertEqual(_apply_sudo("df -h"), "df -h")

    def test_compound_and_both_segments(self):
        # oba root-segmenty dostanou sudo zvlášť (ne sudo sh -c)
        self.assertEqual(
            _apply_sudo("journalctl --rotate && journalctl --vacuum-time=7d"),
            "sudo -n journalctl --rotate && sudo -n journalctl --vacuum-time=7d",
        )

    def test_pipeline_only_first(self):
        # du pod sudo, sort/head jako neprivilegovaný uživatel
        out = _apply_sudo("du -sh /var/* 2>/dev/null | sort -rh | head -20")
        self.assertEqual(out, "sudo -n du -sh /var/* 2>/dev/null | sort -rh | head -20")

    def test_no_sudo_sh_c_wrapping(self):
        # nikdy neobalovat celé do sudo sh -c
        self.assertNotIn("sh -c", _apply_sudo("systemctl restart x && mount -a"))


class TestBuildSshCmd(unittest.TestCase):
    def test_root_user_no_sudo_prefix(self):
        # zpětná kompatibilita: jako root se příkaz nechává verbatim
        cmd = build_ssh_cmd("host1", "systemctl restart x", user="root")
        self.assertEqual(cmd[-1], "systemctl restart x")

    def test_nonroot_user_gets_sudo(self):
        cmd = build_ssh_cmd("host1", "systemctl restart x", user="sentinel")
        self.assertEqual(cmd[-1], "sudo -n systemctl restart x")
        self.assertEqual(cmd[-2], "sentinel@host1")

    def test_nonroot_diagnostic_no_sudo(self):
        cmd = build_ssh_cmd("host1", "df -h", user="sentinel")
        self.assertEqual(cmd[-1], "df -h")


if __name__ == "__main__":
    unittest.main(verbosity=2)
