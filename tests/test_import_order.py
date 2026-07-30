"""Regrese: fasáda `state` musí být úplná bez ohledu na pořadí importů.

`config.load_config()` běží při importu configu a dřív si tahal fasádu
`state`. Když se jako první importoval `state_agents`, spustilo to import
fasády uprostřed jeho inicializace — `from .state_agents import *` pak
zkopírovalo jen část jmen a `state` přišel o ~60 funkcí.

Selhalo to až za běhu (AttributeError) a jen při některém pořadí importů,
takže se to dlouho schovávalo. Test to kontroluje v samostatném procesu,
protože jednou naimportované moduly už v paměti zůstanou.
"""
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Funkce z každého sub-modulu fasády — kdyby se `import *` utnul, zmizí.
_PROBE = (
    "auto_resolve_old_problems",   # state_agents
    "save_problem",                # state_issues
    "init_db",                     # state_base
)


def _facade_names(preamble: str) -> set:
    """Naimportuje state po `preamble` v čistém procesu a vrátí jeho jména."""
    code = (
        f"import sys; sys.path.insert(0, {_ROOT!r})\n"
        f"{preamble}\n"
        "from sentinel import state\n"
        "print(' '.join(n for n in dir(state) if not n.startswith('_')))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=120)
    if out.returncode != 0:
        raise AssertionError(f"import selhal: {out.stderr[-600:]}")
    return set(out.stdout.split())


class TestFacadeCompleteness(unittest.TestCase):
    ORDERS = {
        "state první": "from sentinel import state",
        "state_agents první": "import sentinel.state_agents",
        "config první": "import sentinel.config",
        "utils první": "import sentinel.utils",
        "state_issues první": "import sentinel.state_issues",
        "state_base první": "import sentinel.state_base",
    }

    def test_probe_symbols_present_in_every_order(self):
        for label, preamble in self.ORDERS.items():
            with self.subTest(order=label):
                names = _facade_names(preamble)
                for sym in _PROBE:
                    self.assertIn(sym, names, f"{label}: chybí {sym}")

    def test_name_count_identical_across_orders(self):
        """Nejen vybrané funkce — celá fasáda musí být stejná."""
        baseline = _facade_names(self.ORDERS["state první"])
        for label, preamble in self.ORDERS.items():
            with self.subTest(order=label):
                missing = baseline - _facade_names(preamble)
                self.assertEqual(missing, set(), f"{label}: chybí {sorted(missing)[:10]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
