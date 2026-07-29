"""506: Strukturovaný výstup z AI — robustní extrakce JSON + ask_json().

Projekt měl tři různé regexové implementace, každou jinak rozbitou:
  routes/chat.py  `\\{[^{}]+\\}`  → na vnořeném objektu usekl JSON v půli
  actions.py      `\\{.*\\}` DOTALL → hltavé, sebralo i text za JSONem
  system.py       `\\[.*\\]` DOTALL → totéž pro pole
Autofix (nejčastější AI akce) tím tiše spadl do textového fallbacku.
"""
import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel.chat_service import ChatService, AIResult

_extract = ChatService.extract_json


class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(_extract('{"command":"df -h"}'), {"command": "df -h"})

    def test_markdown_fence(self):
        self.assertEqual(_extract('```json\n{"a":1}\n```'), {"a": 1})
        self.assertEqual(_extract('```\n{"a":1}\n```'), {"a": 1})

    def test_text_around_json(self):
        self.assertEqual(
            _extract('Zde je odpověď:\n{"a":1}\nDoufám, že pomůže.'), {"a": 1})

    def test_nested_object(self):
        """Jádro chyby: `\\{[^{}]+\\}` tady usekl JSON u prvního vnoření."""
        raw = '{"fix":{"cmd":"systemctl restart x","risk":{"score":20}},"ok":true}'
        out = _extract(raw)
        self.assertEqual(out["fix"]["risk"]["score"], 20)
        self.assertTrue(out["ok"])

    def test_braces_inside_string_do_not_break_parsing(self):
        out = _extract('{"cmd":"echo {neni json}","n":1}')
        self.assertEqual(out["cmd"], "echo {neni json}")
        self.assertEqual(out["n"], 1)

    def test_escaped_quote_inside_string(self):
        out = _extract(r'{"msg":"řekl \"ahoj\"","n":2}')
        self.assertEqual(out["n"], 2)

    def test_trailing_prose_is_ignored(self):
        """Hltavý `\\{.*\\}` by sebral i druhý objekt a rozbil parsování."""
        self.assertEqual(_extract('{"a":1}\n\nVysvětlení: {tohle není JSON'), {"a": 1})

    def test_array_mode(self):
        out = _extract('[{"name":"a"},{"name":"b"}]', expect='array')
        self.assertEqual([x["name"] for x in out], ["a", "b"])

    def test_returns_none_when_no_json(self):
        for bad in ["", None, "žádný JSON tady není", "{nedokončený"]:
            self.assertIsNone(_extract(bad), f"{bad!r} má vrátit None")

    def test_invalid_json_returns_none_not_raises(self):
        self.assertIsNone(_extract('{"a": chybí uvozovky}'))


class _Svc(ChatService):
    """Instance bez __init__ — testujeme jen ask_json nad execute_ollama."""
    def __init__(self, replies):
        self._replies = list(replies)

    def execute_ollama(self, prompt, **kw):
        return self._replies.pop(0)


class TestAskJson(unittest.TestCase):
    def test_success_first_try(self):
        svc = _Svc([AIResult('{"command":"df -h","confidence":80}')])
        ok, data, _ = svc.ask_json("p", required_keys=["command"])
        self.assertTrue(ok)
        self.assertEqual(data["confidence"], 80)

    def test_retries_once_on_garbage_then_succeeds(self):
        svc = _Svc([AIResult("Nevím, zkusím to jinak."), AIResult('{"command":"ls"}')])
        ok, data, _ = svc.ask_json("p", required_keys=["command"])
        self.assertTrue(ok, "druhý pokus s korekcí musí projít")
        self.assertEqual(data["command"], "ls")

    def test_retry_prompt_contains_correction(self):
        svc = _Svc([AIResult("blabla"), AIResult('{"a":1}')])
        seen = []
        orig = svc.execute_ollama
        def spy(prompt, **kw):
            seen.append(prompt)
            return orig(prompt, **kw)
        svc.execute_ollama = spy
        svc.ask_json("původní dotaz")
        self.assertEqual(len(seen), 2)
        self.assertIn("POUZE JSON", seen[1])

    def test_gives_up_after_second_failure(self):
        svc = _Svc([AIResult("nic"), AIResult("zase nic")])
        ok, data, raw = svc.ask_json("p")
        self.assertFalse(ok)
        self.assertIsNone(data)
        self.assertEqual(raw, "zase nic")

    def test_missing_required_key_triggers_retry(self):
        svc = _Svc([AIResult('{"description":"jen popis"}'), AIResult('{"command":"ls"}')])
        ok, data, _ = svc.ask_json("p", required_keys=["command"])
        self.assertTrue(ok)
        self.assertEqual(data["command"], "ls")

    def test_ai_error_does_not_retry(self):
        """Když je AI nedostupná, opakování nemá smysl — šetři NPU."""
        svc = _Svc([AIResult.failure("Chyba spojení s AI: timeout")])
        ok, data, _ = svc.ask_json("p")
        self.assertFalse(ok)
        self.assertIsNone(data)
        self.assertEqual(len(svc._replies), 0, "nesmí se volat podruhé")

    def test_array_expectation(self):
        svc = _Svc([AIResult('[{"name":"x","pattern":"y"}]')])
        ok, data, _ = svc.ask_json("p", expect='array')
        self.assertTrue(ok)
        self.assertEqual(data[0]["name"], "x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
