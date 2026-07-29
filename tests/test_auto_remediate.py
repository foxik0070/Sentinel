"""Regrese: _try_auto_remediate padal na NameError (check_command_allowed).

Funkce je definovaná ve state_agents, ale state_issues ji volal nekvalifikovaně —
každý pokus o auto-remediaci skončil v except s
'name check_command_allowed is not defined' (5x v produkčním logu za týden).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state_issues


class TestAutoRemediateAllowlist(unittest.TestCase):
    def test_allowlist_check_is_reached_without_nameerror(self):
        """storage_detector → 'mount -a' → musí dojít až na kontrolu allowlistu."""
        allow = MagicMock(return_value=None)   # není v allowlistu → early return
        with patch.object(state_issues, "has_auto_remediation_attempted", return_value=False), \
             patch("sentinel.state_agents.check_command_allowed", allow), \
             patch.object(state_issues, "logger"):
            state_issues._try_auto_remediate("K|1", "host1", "storage_detector", "mount failed", {})
        allow.assert_called_once_with("mount -a")

    def test_not_auto_execute_does_not_run_ssh(self):
        """Pravidlo bez auto_execute=1 se nesmí spustit přes SSH."""
        allow = MagicMock(return_value={"pattern": "mount -a", "auto_execute": 0})
        with patch.object(state_issues, "has_auto_remediation_attempted", return_value=False), \
             patch("sentinel.state_agents.check_command_allowed", allow), \
             patch("sentinel.actions.run_ssh_command_real") as ssh, \
             patch.object(state_issues, "logger"):
            state_issues._try_auto_remediate("K|2", "host1", "storage_detector", "mount failed", {})
        allow.assert_called_once()
        ssh.assert_not_called()

    def test_blocked_by_safety_classifier_does_not_run_ssh(self):
        """I s auto_execute=1 musí safety klasifikátor zastavit rizikový příkaz."""
        allow = MagicMock(return_value={"pattern": "mount -a", "auto_execute": 1})
        with patch.object(state_issues, "has_auto_remediation_attempted", return_value=False), \
             patch("sentinel.state_agents.check_command_allowed", allow), \
             patch("sentinel.safety.is_blocked", return_value=True), \
             patch("sentinel.actions.run_ssh_command_real") as ssh, \
             patch.object(state_issues, "logger"):
            state_issues._try_auto_remediate("K|3", "host1", "storage_detector", "mount failed", {})
        ssh.assert_not_called()

    def test_already_attempted_is_skipped(self):
        """Druhý pokus o stejný klíč se nesmí opakovat."""
        allow = MagicMock()
        with patch.object(state_issues, "has_auto_remediation_attempted", return_value=True), \
             patch("sentinel.state_agents.check_command_allowed", allow):
            state_issues._try_auto_remediate("K|4", "host1", "storage_detector", "x", {})
        allow.assert_not_called()

    def test_availability_detector_never_remediates(self):
        """Nedostupný host se nedá opravit SSH příkazem — musí skončit dřív."""
        allow = MagicMock()
        with patch.object(state_issues, "has_auto_remediation_attempted", return_value=False), \
             patch("sentinel.state_agents.check_command_allowed", allow):
            state_issues._try_auto_remediate("K|5", "h", "availability_detector", "down", {})
        allow.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
