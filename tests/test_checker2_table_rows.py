import pathlib
import tempfile
import unittest

from tools.checker2 import cli, table_rows

TEST_SRC = ["import time", "def go(self):", "    time.sleep(0.005)", "    self.assertEqual(len(calls), 1)", "    x = a | b"]
SOURCES = {"T": TEST_SRC, "P": ["LIMIT = 10.0", "def f():", "    return LIMIT"]}
HEAD = ("| Covers | Class | Quoted code (verbatim, T = tests/t.py, P = src/p.py) | What the quoted lines do | "
        "Assertion that proves a stated fact (verbatim) | Decision |\n|---|---|---|---|---|---|\n")


def row(covers=":3", cls="POLL", quoted="`T:3  time.sleep(0.005)`", does="The loop calls `time.sleep(0.005)`.",
        asserts="—", decision="OK"):
    return f"| {covers} | {cls} | {quoted} | {does} | {asserts} | {decision} |\n"


def run(rows, grep=None, extra=""):
    return table_rows.check(HEAD + rows + extra, SOURCES, grep)


class TableRowsTest(unittest.TestCase):
    def test_a_literal_row_passes(self):
        good = row() + row(covers=":4", quoted="`T:3  time.sleep(0.005)`", does="Sleeps 0.005.",
                           asserts="`T:4  self.assertEqual(len(calls), 1)`", decision="KEPT")
        self.assertEqual(run(good), (2, []))

    def test_pipe_in_a_quoted_line_is_escaped(self):
        self.assertEqual(run(row(covers=":5", quoted="`T:5  x = a \\| b`", does="Assigns `x`.")), (1, []))

    def test_no_table_means_no_problems(self):
        self.assertEqual(table_rows.check("# brief\n\ntext", SOURCES), (0, []))

    def test_each_failure_class_is_reported(self):
        cases = {
            "Q": row(quoted="`T:3  time.sleep(0.5)`"),
            "B": row(does="The loop calls `time.sleep(0.5)`."),
            "D": row(does="Sleeps 7 seconds."),
            "G": row(does="The wait never ends."),
            "H": row(asserts="`T:3  time.sleep(0.005)`"),
            "A": row(covers=":99", quoted="`T:99  nothing`"),
            "R": row(quoted="no quote"),
            "R2": row(decision="GOOD"),
        }
        for code, text in cases.items():
            with self.subTest(code=code):
                fails = run(text)[1]
                self.assertTrue(fails, code)
                self.assertTrue(any(f" {code[0]} " in f or f": {code[0]} " in f for f in fails), (code, fails))

    def test_overclaim_words_are_rejected_in_every_text_column(self):
        for bad in ("always", "at most", "guarantee", "margin", "only", "must", "turns into", "nominal"):
            with self.subTest(word=bad):
                self.assertTrue(run(row(does=f"Sleeps 0.005, {bad} here."))[1])
        self.assertTrue(run(row(cls="never"))[1])

    def test_coverage_with_a_grep_log(self):
        self.assertEqual(run(row(covers=":3"), "3:    time.sleep(0.005)\n")[1], [])
        self.assertTrue(run(row(covers=":3"), "3:x\n5:y\n")[1])
        self.assertEqual(run(row(covers=":3"), "3:x\n5:y\n", extra="\nname-only lines: 5\n")[1], [])

    def test_problems_reads_sources_from_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel, lines in (("tests/t.py", TEST_SRC), ("src/p.py", SOURCES["P"])):
                path = pathlib.Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual(table_rows.problems(HEAD + row(), tmp, {}), [])
            self.assertTrue(table_rows.problems(HEAD + row(does="always"), tmp, {}))
            self.assertTrue(table_rows.problems(HEAD.replace("T = tests/t.py", "T = tests/none.py") + row(), tmp, {}))
            self.assertEqual(table_rows.problems("no table", tmp, {}), [])

    def test_the_cli_reports_a_table_item(self):
        self.assertTrue(hasattr(cli, "table_rows"))


if __name__ == "__main__":
    unittest.main()
