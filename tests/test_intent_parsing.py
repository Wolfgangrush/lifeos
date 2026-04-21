"""
Paraphrase regression tests for the Telegram bot's deterministic parsers.

These are the patterns the bot must handle *without* relying on Ollama — the
LLM classifier is fuzzy, so each rigid shape (numeric task refs, durations,
completion claims) has a pattern-based fast path. This file pins the
behaviour so future edits can't silently regress.

Run: python3 -m pytest tests/test_intent_parsing.py   (or python3 tests/test_intent_parsing.py)
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the bot module is importable without actually starting anything.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")


def _get_bot_instance():
    """Build a LifeOS instance with heavy side-effects stubbed out."""
    with patch("database.Database") as _db_cls:
        _db_cls.return_value = MagicMock()
        from pure_telegram_bot_v4 import LifeOS
        return LifeOS()


class NumericTaskReferenceTests(unittest.TestCase):
    """_parse_task_numbers must handle paraphrased numeric references."""

    @classmethod
    def setUpClass(cls):
        cls.bot = _get_bot_instance()

    def assertNums(self, message, expected):
        got = self.bot._parse_task_numbers(message)
        self.assertEqual(got, expected, f"message={message!r}")

    # Exact phrasings from Errors.pdf (2026-04-17) — must always pass.
    def test_pdf_tasks_1_to_4(self):
        self.assertNums("I have completed the tasks 1 to 4", [1, 2, 3, 4])

    def test_pdf_task_6(self):
        self.assertNums("I have also completed the task 6", [6])

    def test_pdf_mark_1(self):
        self.assertNums("Mark 1. As completed", [1])

    # Paraphrase coverage — five variations per concept, Memorae-style casual.
    def test_mark_variants(self):
        self.assertNums("mark 1 done", [1])
        self.assertNums("marked task 2 complete", [2])
        self.assertNums("please mark #3 as done", [3])
        self.assertNums("mark tasks 1 and 2 done", [1, 2])
        self.assertNums("MARK 4 DONE", [4])

    def test_completed_variants(self):
        self.assertNums("completed task 5", [5])
        self.assertNums("I completed 2 and 3", [2, 3])
        self.assertNums("yo just wrapped up task 1 and 2", None)  # no "complete/done/finish" keyword
        self.assertNums("finished tasks 1 through 5", [1, 2, 3, 4, 5])
        self.assertNums("done with 1, 2, and 3", [1, 2, 3])

    def test_range_variants(self):
        self.assertNums("mark 1-4 done", [1, 2, 3, 4])
        self.assertNums("complete tasks 2 to 5", [2, 3, 4, 5])
        self.assertNums("done with items 1 thru 3", [1, 2, 3])
        self.assertNums("finish 1–3 please", [1, 2, 3])  # en-dash
        self.assertNums("mark tasks 1 through 3 complete", [1, 2, 3])

    # Must NOT misfire on these.
    def test_negative_cases(self):
        self.assertIsNone(self.bot._parse_task_numbers("what are my tasks"))
        self.assertIsNone(self.bot._parse_task_numbers("I finished my dinner"))
        self.assertIsNone(self.bot._parse_task_numbers("how is my day going"))
        self.assertIsNone(self.bot._parse_task_numbers("add a task to call mom"))
        self.assertIsNone(self.bot._parse_task_numbers("I ate 3 apples"))


class DurationParsingTests(unittest.TestCase):
    """_parse_duration_minutes captures time spent on a task."""

    @classmethod
    def setUpClass(cls):
        cls.bot = _get_bot_instance()

    def test_minutes(self):
        self.assertEqual(self.bot._parse_duration_minutes("done in 20 min"), 20)
        self.assertEqual(self.bot._parse_duration_minutes("took 45 minutes"), 45)
        self.assertEqual(self.bot._parse_duration_minutes("spent 15m"), 15)

    def test_hours(self):
        self.assertEqual(self.bot._parse_duration_minutes("took 2 hours"), 120)
        self.assertEqual(self.bot._parse_duration_minutes("2h30m"), 150)
        self.assertEqual(self.bot._parse_duration_minutes("1.5 hr"), 90)

    def test_no_duration(self):
        self.assertIsNone(self.bot._parse_duration_minutes("task 1 done"))
        self.assertIsNone(self.bot._parse_duration_minutes(""))
        self.assertIsNone(self.bot._parse_duration_minutes("finished"))


class CompletionProofTests(unittest.TestCase):
    """_looks_like_completion_proof gates the multimodal auto-close path."""

    @classmethod
    def setUpClass(cls):
        cls.bot = _get_bot_instance()

    def test_positive(self):
        self.assertTrue(self.bot._looks_like_completion_proof("signed insurance form"))
        self.assertTrue(self.bot._looks_like_completion_proof("submitted"))
        self.assertTrue(self.bot._looks_like_completion_proof("paid the stamp paper"))
        self.assertTrue(self.bot._looks_like_completion_proof("picked up the clothes"))
        self.assertTrue(self.bot._looks_like_completion_proof("done — here's the receipt"))

    def test_negative(self):
        self.assertFalse(self.bot._looks_like_completion_proof(""))
        self.assertFalse(self.bot._looks_like_completion_proof("check this out"))
        self.assertFalse(self.bot._looks_like_completion_proof("just a photo"))


class EfficiencyNoteTests(unittest.TestCase):
    """_efficiency_note builds the actual-vs-estimated tail shown on completion."""

    @classmethod
    def setUpClass(cls):
        cls.bot = _get_bot_instance()

    def test_faster_than_estimate(self):
        note = self.bot._efficiency_note(actual=10, estimated=20)
        self.assertIn("faster", note)

    def test_slower_than_estimate(self):
        note = self.bot._efficiency_note(actual=40, estimated=20)
        self.assertIn("slower", note)

    def test_on_par(self):
        note = self.bot._efficiency_note(actual=20, estimated=20)
        self.assertIn("on par", note)

    def test_missing_either(self):
        self.assertEqual(self.bot._efficiency_note(None, None), "")
        self.assertIn("est", self.bot._efficiency_note(None, 30))
        self.assertIn("took", self.bot._efficiency_note(25, None))


if __name__ == "__main__":
    unittest.main()
