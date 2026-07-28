"""507: AIResult — výsledek AI volání se strojově čitelným příznakem úspěchu.

execute_ollama() vracelo chyby jako běžný text ("Chyba spojení s AI: …"),
takže volající musel hádat podle prefixu. Když se znění změnilo, chybová
hláška se uložila jako obsah (digest, runbook, postmortem).
AIResult dědí ze str → všech ~19 volajících funguje beze změny.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel.chat_service import AIResult, ChatService


class TestAIResultIsString(unittest.TestCase):
    """Zpětná kompatibilita — existující volající s tím pracují jako se str."""

    def test_is_str_instance(self):
        self.assertIsInstance(AIResult("odpověď"), str)

    def test_string_operations_work(self):
        r = AIResult("  Disk je plný.  ")
        self.assertEqual(r.strip(), "Disk je plný.")
        self.assertEqual(len(AIResult("abc")), 3)
        self.assertTrue(AIResult("abc").startswith("a"))
        self.assertEqual(AIResult("a") + "b", "ab")
        self.assertEqual(f"{AIResult('x')}!", "x!")
        self.assertEqual(AIResult("a,b").split(","), ["a", "b"])

    def test_equality_with_plain_str(self):
        self.assertEqual(AIResult("text"), "text")

    def test_none_becomes_empty(self):
        self.assertEqual(AIResult(None), "")

    def test_falsy_when_empty(self):
        self.assertFalse(AIResult(""))
        self.assertTrue(AIResult("x"))


class TestAIResultFlags(unittest.TestCase):
    def test_success_defaults_to_ok(self):
        r = AIResult("odpověď")
        self.assertTrue(r.ok)
        self.assertEqual(r.error, "")

    def test_failure_marks_not_ok(self):
        r = AIResult.failure("Chyba spojení s AI: timeout")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "Chyba spojení s AI: timeout")
        self.assertEqual(str(r), "Chyba spojení s AI: timeout")

    def test_explicit_ok_false(self):
        self.assertFalse(AIResult("cokoliv", ok=False).ok)


class TestAiReplyOk(unittest.TestCase):
    """Guard, který brání uložení chybové hlášky jako obsahu."""

    def test_accepts_valid_reply(self):
        self.assertTrue(ChatService._ai_reply_ok(AIResult("Restartuj službu.")))
        self.assertTrue(ChatService._ai_reply_ok("prostý text odpovědi"))

    def test_rejects_failure_flag(self):
        self.assertFalse(ChatService._ai_reply_ok(AIResult.failure("cokoliv")))

    def test_rejects_failure_even_with_innocent_text(self):
        """Jádro 507: chyba bez známého prefixu se dřív tvářila jako odpověď."""
        self.assertFalse(ChatService._ai_reply_ok(
            AIResult("Model neodpověděl", ok=False)))

    def test_prefix_fallback_still_works(self):
        for bad in ["Chyba spojení s AI: x", "AI Error: y"]:
            self.assertFalse(ChatService._ai_reply_ok(bad))

    def test_rejects_empty(self):
        for empty in ["", "   ", None, AIResult("")]:
            self.assertFalse(ChatService._ai_reply_ok(empty))


if __name__ == "__main__":
    unittest.main(verbosity=2)
