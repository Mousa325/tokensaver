import pathlib
import tempfile
import unittest

from tools.checker2 import budget, request


class ConditionsTest(unittest.TestCase):
    def test_test_log_needs_both_run_lines(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "log.txt").write_text("python -m unittest tests.test_x\n", encoding="utf-8")
            self.assertTrue(request.test_log_reasons({"Test log": ["log.txt"]}, root))
            (root / "log.txt").write_text("python -m unittest tests.test_x\ncwd: tests\n", encoding="utf-8")
            self.assertEqual(request.test_log_reasons({"Test log": ["log.txt"]}, root), [])

    def test_approved_by_needs_name_and_time(self):
        self.assertTrue(request.APPROVED.match("owner 2026-11-01T06:17Z"))
        self.assertFalse(request.APPROVED.match("owner"))

    def test_round_ok_lets_a_third_round_through(self):
        state = {"k": {"attempts": 3, "returns": 3}}
        self.assertTrue(budget.problems(state, "k"))
        self.assertEqual(budget.problems(state, "k", round_ok=True), [])


if __name__ == "__main__":
    unittest.main()
