import os
import pathlib
import stat
import tempfile
import unittest

from tools.checker2 import extras, report


def make_venv(root, scripts):
    bin_dir = pathlib.Path(root) / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir(parents=True)
    for name, body in scripts.items():
        path = bin_dir / (name + (".bat" if os.name == "nt" else ""))
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(root)


class ExtrasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.repo = self.root / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "m.py").write_text("x = 1\n", encoding="utf-8")
        (self.repo / "rules.yml").write_text("rules: []\n", encoding="utf-8")
        self.work = self.root / "tmp"
        self.work.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_extras_block_is_skipped_not_failed(self):
        items = extras.run_extras({}, str(self.repo), str(self.work))
        self.assertEqual([(i["item"], i["status"]) for i in items], [("extras", "SKIPPED")])

    def test_every_item_is_report_only(self):
        cfg = {"extras": {"venv": str(self.root / "none"), "hypothesis": {"tests": ["t.py"]},
                          "cosmic_ray": {"module": "src/m.py", "tests": ["t.py"]},
                          "semgrep": {"rules": "rules.yml", "paths": ["src"]}}}
        items = extras.run_extras(cfg, str(self.repo), str(self.work))
        self.assertEqual([i["status"] for i in items], ["SKIPPED"] * 3)
        self.assertTrue(all(i["reasons"] == [] for i in items))
        built = report.build_report(items, [])
        self.assertEqual(built["verdict"], "PASS")

    @unittest.skipIf(os.name == "nt", "stub is a shell script")
    def test_semgrep_runs_on_a_copy_and_counts_findings(self):
        venv = make_venv(self.root / "venv", {"semgrep": '#!/bin/sh\necho \'{"results":[{},{}],"errors":[]}\'\n'})
        cfg = {"extras": {"venv": venv, "semgrep": {"rules": "rules.yml", "paths": ["src"]}}}
        out = self.root / "out"
        items = extras.run_extras(cfg, str(self.repo), str(self.work), out)
        self.assertEqual((items[0]["status"], items[0]["detail"]), ("INFO", "findings 2; errors 0"))
        self.assertTrue((out / "extras-semgrep.txt").is_file())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_missing_target_is_skipped_and_repo_untouched(self):
        venv = make_venv(self.root / "venv", {"semgrep": "#!/bin/sh\nexit 0\n"})
        cfg = {"extras": {"venv": venv, "semgrep": {"rules": "rules.yml", "paths": ["nope"]}}}
        before = sorted(str(p) for p in self.repo.rglob("*"))
        items = extras.run_extras(cfg, str(self.repo), str(self.work))
        self.assertEqual(items[0]["status"], "SKIPPED")
        self.assertEqual(sorted(str(p) for p in self.repo.rglob("*")), before)

    def test_copy_into_keeps_paths_and_reports_missing(self):
        dest = self.root / "dest"
        dest.mkdir()
        missing = extras.copy_into(str(self.repo), ["src", "ghost.py"], dest)
        self.assertEqual(missing, ["ghost.py"])
        self.assertTrue((dest / "src" / "m.py").is_file())

    @unittest.skipIf(os.name == "nt", "stub is a shell script")
    def test_cosmic_ray_exec_timeout_reports_partial_counts(self):
        (self.repo / "t.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
        venv = make_venv(self.root / "venv", {
            "python": "#!/bin/sh\nexit 0\n",
            "cosmic-ray": '#!/bin/sh\n[ "$1" = exec ] && sleep 5\nexit 0\n',
            "cr-report": "#!/bin/sh\necho 'total jobs: 40'\necho 'surviving mutants: 2 (5.00%)'\n",
            "cr-rate": "#!/bin/sh\necho 5.00\n"})
        cfg = {"extras": {"venv": venv, "timeout_s": 1, "cosmic_ray": {"module": "src/m.py", "tests": ["t.py"]}}}
        items = extras.run_extras(cfg, str(self.repo), str(self.work))
        self.assertEqual(items[0]["detail"],
                         "PARTIAL (exec timeout); mutants 40; surviving 2; survival rate 5.00")

    def test_cli_flag_adds_items_and_keeps_the_verdict_shape(self):
        from tools.checker2 import cli
        parser_help = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
        self.assertIn("--extras", parser_help)
        self.assertIn("extras.run_extras", parser_help)


if __name__ == "__main__":
    unittest.main()
