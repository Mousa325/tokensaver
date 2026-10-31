import pathlib
import tempfile
import unittest

from tools.checker2 import output_guard, write_guard

DIFF = ("--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n"
        "--- a/other/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")


class OutputGuardTest(unittest.TestCase):
    def test_paths_are_read_from_the_diff(self):
        self.assertEqual(output_guard.diff_paths(DIFF), ["src/a.py", "other/gone.py"])

    def test_outside_paths_are_refused(self):
        self.assertEqual(output_guard.refused(DIFF, ["src/"]), ["other/gone.py"])
        self.assertEqual(output_guard.refused(DIFF, ["src/", "other/"]), [])

    def test_empty_list_refuses_all_and_cli_exit_code(self):
        self.assertEqual(output_guard.refused(DIFF, []), ["src/a.py", "other/gone.py"])
        with tempfile.TemporaryDirectory() as tmp:
            allowed = pathlib.Path(tmp) / "allowed.txt"
            diff = pathlib.Path(tmp) / "out.diff"
            allowed.write_text("src/\n", encoding="utf-8")
            diff.write_text(DIFF, encoding="utf-8")
            self.assertEqual(output_guard.main([str(allowed), str(diff)]), 1)


class WriteGuardTest(unittest.TestCase):
    def test_refuses_paths_outside_the_list(self):
        self.assertEqual(write_guard.refused(["src/a.py", "docs/x.md"], ["src/"]), ["docs/x.md"])
        self.assertEqual(write_guard.refused(["src/a.py"], []), ["src/a.py"])


if __name__ == "__main__":
    unittest.main()
