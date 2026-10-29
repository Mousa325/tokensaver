import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tools.checker2 import cli, core, env_check, package_check
from tools.checker2 import report as report_mod


def make_repo(tmp, branch):
    subprocess.run(["git", "-C", tmp, "init", "-q", "-b", branch], check=True)
    subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)


class LiveStateTest(unittest.TestCase):
    def test_wrong_branch_and_lock_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp, "main")
            lock = pathlib.Path(tmp) / "LOCK"
            lock.write_text("x", encoding="utf-8")
            problems = core.live_state(tmp, "feature", lock)
            self.assertTrue(any("branch is 'main'" in p for p in problems))
            self.assertTrue(any("stale lock" in p for p in problems))

    def test_clean_state_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp, "main")
            self.assertEqual(core.live_state(tmp, "main", pathlib.Path(tmp) / "nolock"), [])


class SealTest(unittest.TestCase):
    def test_seal_detects_a_changed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = pathlib.Path(tmp)
            (pkg / "brief.md").write_text("one", encoding="utf-8")
            core.seal(pkg, "T1", 1, "8afc944")
            self.assertEqual(core.check_seal(pkg), [])
            (pkg / "brief.md").write_text("two", encoding="utf-8")
            self.assertEqual(core.check_seal(pkg), ["brief.md"])


class ReplyCheckTest(unittest.TestCase):
    def test_open_and_missing_rows_are_refused(self):
        rows = [{"site": "a", "answer": "fixed"}, {"site": "b", "answer": " "}]
        problems = core.reply_check(["a", "b", "c"], rows)
        self.assertEqual(problems, ["open row for site b", "no row for site c"])


if __name__ == "__main__":
    unittest.main()


class ScopeTest(unittest.TestCase):
    def test_path_outside_allowed_paths_is_found(self):
        patch = "+++ b/tools/checker2/core.py\n+++ b/src/other.py\n"
        self.assertEqual(core.out_of_scope(patch, ["tools/checker2/", "tests/test_checker2.py"]), "src/other.py")
        self.assertIsNone(core.out_of_scope("+++ b/tools/checker2/core.py\n", ["tools/checker2/"]))


class LockHolderTest(unittest.TestCase):
    def test_live_and_stale_locks_are_told_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp, "main")
            live = pathlib.Path(tmp) / "live.lock"
            live.write_text(f"pid={os.getpid()} utc=x\n", encoding="utf-8")
            stale = pathlib.Path(tmp) / "stale.lock"
            stale.write_text("pid=999999 utc=x\n", encoding="utf-8")
            self.assertIn(f"lock held by a live job: {live}", core.live_state(tmp, "main", live))
            self.assertIn(f"stale lock: {stale}", core.live_state(tmp, "main", stale))


class GateTest(unittest.TestCase):
    def test_command_must_exit_zero_and_print_expected_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(core.gate_passes("python3 -c \"print('READY')\"", "READY", tmp))
            self.assertFalse(core.gate_passes("python3 -c \"print('READY')\"", "DONE", tmp))
            self.assertFalse(core.gate_passes("python3 -c \"import sys; print('READY'); sys.exit(1)\"", "READY", tmp))


class ReportTest(unittest.TestCase):
    def test_reasons_make_a_returned_report_with_exit_2(self):
        results = [
            {"item": "seal", "status": "PASS", "reasons": []},
            {"item": "scope", "status": "FAIL", "reasons": [{"rule": "scope", "item": "scope", "fix": "move src/x.py"}]},
        ]
        report = report_mod.build_report(results, ["stale lock check by a human"])
        self.assertEqual(report["verdict"], "RETURNED")
        self.assertEqual(report_mod.exit_code(report), 2)
        self.assertEqual(report["unverified"], ["stale lock check by a human"])

    def test_no_reasons_is_pass_with_exit_0(self):
        report = report_mod.build_report([{"item": "seal", "status": "PASS", "reasons": []}], [])
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report_mod.exit_code(report), 0)


class PackageCheckTest(unittest.TestCase):
    def test_sums_and_sizes_must_match_the_files(self):
        import hashlib
        files = {"a.py": b"x = 1\n"}
        sha = hashlib.sha256(files["a.py"]).hexdigest()
        self.assertEqual(package_check.sums_sizes_problems(files, f"{sha}  a.py\n", "6 a.py\n"), [])
        self.assertEqual(package_check.sums_sizes_problems(files, f"{'0' * 64}  a.py\n", "6 a.py\n"),
                         ["a.py sha mismatch"])
        self.assertEqual(package_check.sums_sizes_problems(files, f"{sha}  a.py\n", "9 a.py\n"),
                         ["a.py size mismatch"])

    def test_result_rows_are_required_for_every_rule(self):
        rules = ["R1", "R2", "R3"]
        rows = "| R1 | ok |\n| R2 | ok |\n"
        self.assertEqual(package_check.result_rows_missing(rows, rules), ["R3"])
        self.assertEqual(package_check.result_rows_missing(rows + "| R3 |  |\n", rules), ["R3"])


class EnvAndRunTest(unittest.TestCase):
    def test_env_refuses_relative_python_short_disk_and_autocrlf(self):
        problems = env_check.env_problems("python3", 10**18, "/tmp", "true")
        self.assertTrue(any("absolute" in p for p in problems))
        self.assertTrue(any("free disk" in p for p in problems))
        self.assertTrue(any("autocrlf" in p for p in problems))
        self.assertEqual(env_check.env_problems(sys.executable, 1, "/tmp", "false"), [])

    def test_full_run_passes_a_clean_package_and_returns_a_bad_one(self):
        import hashlib
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as pkg:
            make_repo(repo, "main")
            lock = pathlib.Path(repo) / "no.lock"
            config = {"repo": repo, "expected_branch": "main", "lock_file": str(lock),
                      "python": sys.executable, "min_free_bytes": 1}
            body = b"print(1)\n"
            (pathlib.Path(pkg) / "x.py").write_bytes(body)
            digest = hashlib.sha256(body).hexdigest()
            (pathlib.Path(pkg) / "SHA256SUMS.txt").write_text(f"{digest}  x.py\n", encoding="utf-8")
            (pathlib.Path(pkg) / "SIZES.txt").write_text(f"{len(body)} x.py\n", encoding="utf-8")
            brief = "| R1 | ok |\n"
            good = cli.run(config, pkg, brief, "/tmp")
            self.assertEqual(good["verdict"], "PASS")
            (pathlib.Path(pkg) / "x.py").write_bytes(b"changed\n")
            bad = cli.run(config, pkg, brief, "/tmp")
            self.assertEqual(bad["verdict"], "RETURNED")
            self.assertTrue(any(r["rule"] == "package" for r in bad["reasons"]))


class AbandonAndMergeTest(unittest.TestCase):
    def test_last_start_without_end_is_abandoned(self):
        log = "t1 start task-a\nt2 end task-a exit=0\nt3 start task-b\n"
        self.assertTrue(core.job_abandoned(log, "task-b"))
        self.assertFalse(core.job_abandoned(log, "task-a"))
        self.assertFalse(core.job_abandoned(log, "task-missing"))

    def test_merge_refused_after_the_package_changes(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as pkg:
            make_repo(repo, "main")
            lock = pathlib.Path(repo) / "no.lock"
            (pathlib.Path(pkg) / "a.txt").write_text("one", encoding="utf-8")
            core.seal(pkg, "T1", 1, "8afc944")
            self.assertEqual(core.merge_problems(repo, "main", lock, pkg), [])
            (pathlib.Path(pkg) / "a.txt").write_text("two", encoding="utf-8")
            self.assertEqual(core.merge_problems(repo, "main", lock, pkg), ["seal voided by change: a.txt"])


class ResultRowsPerFileTest(unittest.TestCase):
    def test_every_changed_file_needs_every_rule(self):
        rules = ["R1", "R2", "R3"]
        rows = "".join(f"| {rule} | tools/x.py | ok |\n" for rule in rules)
        self.assertEqual(package_check.result_rows_missing_per_file(rows, ["tools/x.py"], rules), [])
        self.assertEqual(package_check.result_rows_missing_per_file(rows, ["tools/x.py", "tools/y.py"], rules)[0],
                         ("tools/y.py", "R1"))
        self.assertEqual(package_check.changed_paths("+++ b/a.py\n--- a/a.py\n"), ["a.py"])


class OperatorScopeCitedSweepTest(unittest.TestCase):
    def test_operator_scope_and_cited_files_in_cli(self):
        import hashlib
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as pkg:
            make_repo(repo, "main")
            body = b"print(1)\n"
            pkgp = pathlib.Path(pkg)
            (pkgp / "x.py").write_bytes(body)
            (pkgp / "p.diff").write_text("+++ b/src/evil.py\n", encoding="utf-8")
            (pkgp / "SHA256SUMS.txt").write_text(
                f"{hashlib.sha256(body).hexdigest()}  x.py\n"
                f"{hashlib.sha256((pkgp / 'p.diff').read_bytes()).hexdigest()}  p.diff\n", encoding="utf-8")
            (pkgp / "SIZES.txt").write_text(f"{len(body)} x.py\n{(pkgp / 'p.diff').stat().st_size} p.diff\n",
                                            encoding="utf-8")
            config = {"repo": repo, "expected_branch": "main", "lock_file": str(pathlib.Path(repo) / "no.lock"),
                      "python": sys.executable, "min_free_bytes": 1, "operator_field": "Operator:",
                      "allowed_paths": ["tools/"]}
            brief = "Operator: Owner\n- cited: x.py\n"
            result = cli.run(config, pkg, brief, "/tmp")
            by_item = {c["item"]: c["status"] for c in result["checks"]}
            self.assertEqual(by_item["operator"], "PASS")
            self.assertEqual(by_item["cited"], "PASS")
            self.assertEqual(by_item["scope"], "FAIL")
            missing_op = cli.run(config, pkg, "- cited: x.py\n", "/tmp")
            self.assertEqual({c["item"]: c["status"] for c in missing_op["checks"]}["operator"], "FAIL")

    def test_unlisted_sweep_hits_are_reported(self):
        texts = {"a.py": "x = eval(s)\ny = 1\n", "b.py": "z = eval(t)\n"}
        self.assertEqual(core.unlisted_hits(r"eval\(", texts, {"a.py:1"}), ["b.py:1"])


class GitUnreachableTest(unittest.TestCase):
    def test_missing_checkout_is_unverified_not_a_branch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = core.live_state(os.path.join(tmp, "not-a-repo"), "main", pathlib.Path(tmp) / "no.lock")
            self.assertEqual(len(problems), 1)
            self.assertTrue(problems[0].startswith("UNVERIFIED: no git checkout"))


class RequestInCliTest(unittest.TestCase):
    def test_request_item_is_checked_when_given(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as pkg:
            make_repo(repo, "main")
            config = {"repo": repo, "expected_branch": "main", "lock_file": str(pathlib.Path(repo) / "no.lock"),
                      "python": sys.executable, "min_free_bytes": 1}
            head = "From: planner\nTo: owner\nSent: 2026-10-26T12:00:00Z\nBasic idea: x\nTask scope: x\n"
            result = cli.run(config, pkg, None, "/tmp", head)
            self.assertEqual({c["item"]: c["status"] for c in result["checks"]}["request"], "PASS")
            bad = cli.run(config, pkg, None, "/tmp", head.replace("To: owner", "To: nobody"))
            self.assertEqual({c["item"]: c["status"] for c in bad["checks"]}["request"], "FAIL")


class AbandonVsRunningTest(unittest.TestCase):
    def test_live_job_lock_means_running_not_abandoned(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as pkg:
            make_repo(repo, "main")
            log = pathlib.Path(repo) / "runner.log"
            log.write_text("t1 start task-x\n", encoding="utf-8")
            job_lock = pathlib.Path(repo) / "job-task-x.lock"
            config = {"repo": repo, "expected_branch": "main", "lock_file": str(pathlib.Path(repo) / "no.lock"),
                      "python": sys.executable, "min_free_bytes": 1, "runner_log": str(log), "task_id": "task-x",
                      "job_lock": str(job_lock)}
            job_lock.write_text(f"pid={os.getpid()} utc=x\n", encoding="utf-8")
            running = cli.run(config, pkg, None, "/tmp")
            self.assertEqual({c["item"]: c["status"] for c in running["checks"]}["abandon"], "RUNNING")
            job_lock.write_text("pid=999999 utc=x\n", encoding="utf-8")
            stopped = cli.run(config, pkg, None, "/tmp")
            self.assertEqual({c["item"]: c["status"] for c in stopped["checks"]}["abandon"], "FAIL")
