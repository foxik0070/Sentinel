"""Regrese: `run_ssh_command_real` musí být volatelná.

Chyba, kterou to hlídá: lokální `from . import safety` uvnitř funkce udělal
ze `safety` lokální proměnnou pro CELÉ tělo, takže `safety.is_blocked()`
o třicet řádků výš spadlo na UnboundLocalError. Rozbilo to VEŠKERÉ spouštění
SSH příkazů — auto-remediaci, ruční akce i diagnostiku.

938 testů to nezachytilo, protože žádný nevolal `run_ssh_command_real`
až k tomu místu. Tenhle test volá skutečnou funkci s podvrženým subprocess,
takže projde celým tělem včetně všech větví.
"""
import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import actions


class _Result:
    def __init__(self, rc=0, out='ok', err=''):
        self.returncode, self.stdout, self.stderr = rc, out, err


class TestRunSshCommandReal(unittest.TestCase):
    """Prochází se celé tělo funkce — chyba byla mezi řádky, ne v návratu."""

    def setUp(self):
        # DEBUG_MODE by shodilo běh do dry-run větve a minulo test
        self._args = getattr(actions.config, 'ARGS', {})
        actions.config.ARGS = {}

    def tearDown(self):
        actions.config.ARGS = self._args

    def test_internal_readonly_command_executes(self):
        """internal=True přeskočí allowlist, ale musí projít safety kontrolou."""
        with patch.object(actions.subprocess, 'run', return_value=_Result(out='sentinel')):
            ok, out = actions.run_ssh_command_real('docs', 'id -nG', internal=True)
        self.assertTrue(ok)
        self.assertIn('sentinel', out)

    def test_dangerous_command_never_executes(self):
        """Rizikový příkaz spadne do dry-run: vrací True, ale NIC nespustí.

        Právě tady byl chybný import — `safety.is_blocked()` je hned na
        začátku těla funkce.
        """
        with patch.object(actions.subprocess, 'run', return_value=_Result()) as run:
            ok, out = actions.run_ssh_command_real('docs', 'rm -rf /', internal=False)
        self.assertIn('DRY RUN', out)
        run.assert_not_called()          # klíčové: k SSH se to nedostalo

    def test_non_allowlisted_command_blocked_with_explanation(self):
        with patch.object(actions.subprocess, 'run', return_value=_Result()):
            ok, out = actions.run_ssh_command_real(
                'docs', 'nejaky-neznamy-prikaz --flag', internal=False)
        self.assertFalse(ok)
        self.assertIn('BLOCKED', out)

    def test_failed_command_returns_stderr(self):
        with patch.object(actions.subprocess, 'run',
                          return_value=_Result(rc=1, out='', err='permission denied')):
            ok, out = actions.run_ssh_command_real('docs', 'df -h', internal=True)
        self.assertFalse(ok)
        self.assertIn('denied', out)

    def test_timeout_handled(self):
        with patch.object(actions.subprocess, 'run',
                          side_effect=actions.subprocess.TimeoutExpired('ssh', 30)):
            ok, out = actions.run_ssh_command_real('docs', 'df -h', internal=True)
        self.assertFalse(ok)
        self.assertIn('Timeout', out)

    def test_exception_handled(self):
        with patch.object(actions.subprocess, 'run', side_effect=OSError('boom')):
            ok, out = actions.run_ssh_command_real('docs', 'df -h', internal=True)
        self.assertFalse(ok)
        self.assertIn('Exception', out)

    def test_module_level_names_not_shadowed(self):
        """Jádro regrese: lokální import nesmí zastínit modulový.

        Kdyby některá větev znovu importovala `safety`, `state`, `utils`
        nebo `config`, Python by z nich udělal lokální proměnné pro celé
        tělo a dřívější použití by spadlo na UnboundLocalError.
        """
        import inspect
        src = inspect.getsource(actions.run_ssh_command_real)
        for name in ('safety', 'state', 'utils', 'config'):
            self.assertNotIn(f'import {name}', src.replace('from . import policy', ''),
                             f"lokální import '{name}' zastíní modulový — "
                             f"UnboundLocalError na dřívějším použití")

    def test_stdout_kept_on_nonzero_exit(self):
        """`systemctl status` vraci 3 u neběžící jednotky — a text je ve STDOUT.

        Dřív se stdout zahazoval a diagnostika vracela prázdno právě tehdy,
        když problém existoval.
        """
        with patch.object(actions.subprocess, 'run',
                          return_value=_Result(rc=3, out='Active: failed', err='')):
            ok, out = actions.run_ssh_command_real('docs', 'systemctl status x', internal=True)
        self.assertFalse(ok)
        self.assertIn('Active: failed', out)

    def test_both_streams_kept(self):
        with patch.object(actions.subprocess, 'run',
                          return_value=_Result(rc=1, out='vystup', err='varovani')):
            _, out = actions.run_ssh_command_real('docs', 'df -h', internal=True)
        self.assertIn('vystup', out)
        self.assertIn('varovani', out)

    def test_empty_output_reports_exit_code(self):
        with patch.object(actions.subprocess, 'run', return_value=_Result(rc=7, out='', err='')):
            _, out = actions.run_ssh_command_real('docs', 'df -h', internal=True)
        self.assertIn('7', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
