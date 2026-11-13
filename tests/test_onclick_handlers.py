"""Kazdy onclick, ktery server vykresli, musi mit funkci ve frontendu.

Inline komentar u karty issue byl pulka funkce: routes/issues.py vykreslovalo
ikonu s onclick="_icToggle(...)" a skryty radek s _icSubmit/_icHide, ale zadna
z tech tri funkci v JS neexistovala. Klik koncil na ReferenceError a navenek
se nedelo nic — zadna hlaska, zadny pozadavek na server. Staticky to nic
neodhalilo, protoze Python i JS byly samy o sobe v poradku.
"""
import os
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PY_DIRS = [os.path.join(_ROOT, "sentinel"), os.path.join(_ROOT, "sentinel", "routes")]
_STATIC = os.path.join(_ROOT, "sentinel", "static")
_TEMPLATES = os.path.join(_ROOT, "sentinel", "templates")

# Klicova slova jazyka — syntakticky vypadaji jako volani, funkce to nejsou.
_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "new",
    "delete", "void", "var", "let", "const", "function", "else", "do", "try",
    "await", "in", "of", "instanceof",
}

# Vestavene funkce prohlizece a knihoven — nejsou nase, ale existuji.
_BUILTINS = {
    "alert", "confirm", "prompt", "setTimeout", "setInterval", "clearTimeout",
    "clearInterval", "parseInt", "parseFloat", "encodeURIComponent",
    "decodeURIComponent", "fetch", "Number", "String", "Boolean", "Array",
    "Object", "Date", "Math", "JSON", "RegExp", "Error", "Promise", "Set",
    "Map", "isNaN", "btoa", "atob", "require", "Chart", "io",
}
# CSS funkce uvnitr inline stylu (this.style.transform='translateY(…)').
_CSS_FUNCS = {
    "rgb", "rgba", "hsl", "hsla", "calc", "url", "translate", "translateX",
    "translateY", "scale", "rotate", "blur", "linear-gradient",
}
_EXTERNAL = _KEYWORDS | _BUILTINS | _CSS_FUNCS


def _js_sources():
    out = []
    for d, _, files in os.walk(_STATIC):
        for f in files:
            if f.endswith(".js") and not f.endswith(".min.js"):
                out.append(os.path.join(d, f))
    return out


def _defined_functions():
    names = set()
    pat = re.compile(
        r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"      # function f()
        r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("  # const f = (...) =>
        r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function"
        r"|window\.([A-Za-z_$][\w$]*)\s*="                  # window.f = ...
    )
    for path in _js_sources():
        with open(path, encoding="utf-8") as fh:
            for m in pat.finditer(fh.read()):
                names.update(g for g in m.groups() if g)
    return names


def _called_functions(paths, exts):
    """Jmena volana z on*="fn(" atributu."""
    calls = {}
    # V Pythonu se atribut casto sklada uvnitr f-stringu jako onclick=\"...\",
    # tedy s uvozovkou escapovanou zpetnym lomitkem — to musi regex unest,
    # jinak prehledne presne ty handlery, ktere vykresluje server.
    pat = re.compile(r"""on[a-z]+\s*=\s*\\?(["'])(.*?)(?<!\\)\\?\1""", re.S)
    fn = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(")
    for root in paths:
        for d, _, files in os.walk(root):
            for f in files:
                if not f.endswith(exts):
                    continue
                p = os.path.join(d, f)
                with open(p, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                for m in pat.finditer(text):
                    for name in fn.findall(m.group(2)):
                        if name not in _EXTERNAL:
                            calls.setdefault(name, set()).add(os.path.relpath(p, _ROOT))
    return calls


class TestOnclickHandlers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defined = _defined_functions()

    def _assert_all_defined(self, calls, where):
        missing = {n: sorted(src) for n, src in calls.items() if n not in self.defined}
        self.assertEqual(missing, {},
                         f"{where}: onclick volá funkce, které v JS nejsou: {missing}")

    def test_python_rendered_handlers_exist(self):
        # Nejdulezitejsi smer: HTML skladane v Pythonu se nijak nekontroluje.
        self._assert_all_defined(_called_functions(_PY_DIRS, (".py",)), "Python")

    def test_template_handlers_exist(self):
        self._assert_all_defined(_called_functions([_TEMPLATES], (".html",)), "Šablony")

    def test_js_rendered_handlers_exist(self):
        self._assert_all_defined(_called_functions([_STATIC], (".js",)), "JS")

    def test_inline_comment_functions_are_defined(self):
        # Konkretni pripad, ktery tenhle test vyvolal.
        for name in ("_icToggle", "_icSubmit", "_icHide"):
            self.assertIn(name, self.defined, f"{name} chybi ve frontendu")


if __name__ == "__main__":
    unittest.main()
