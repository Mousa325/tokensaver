import pathlib
import tempfile
import unittest

from tools.checker2 import budget


class BudgetTests(unittest.TestCase):
    def test_key_uses_task_header_then_file_stem(self):
        self.assertEqual(budget.task_key({"Task": ["T-9"]}, "x.md"), "T-9")
        self.assertEqual(budget.task_key({}, "req-1.md"), "req-1")

    def test_loop_limit_after_max_returns(self):
        state = {}
        for _ in range(budget.MAX_RETURNS):
            budget.record(state, "k", "RETURN")
        self.assertTrue(any("loop limit" in r for r in budget.problems(state, "k")))
        self.assertEqual(budget.problems(state, "other"), [])

    def test_pass_does_not_count_as_return(self):
        state = {}
        for _ in range(budget.MAX_RETURNS):
            budget.record(state, "k", "PASS")
        self.assertEqual(budget.problems(state, "k"), [])

    def test_budget_limit_after_max_attempts(self):
        state = {}
        for _ in range(budget.MAX_ATTEMPTS):
            budget.record(state, "k", "PASS")
        self.assertTrue(any("budget limit" in r for r in budget.problems(state, "k")))

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "sub" / "state.json"
            self.assertEqual(budget.load(path), {})
            budget.save(path, {"k": {"attempts": 2, "returns": 1}})
            self.assertEqual(budget.load(path), {"k": {"attempts": 2, "returns": 1}})


if __name__ == "__main__":
    unittest.main()
