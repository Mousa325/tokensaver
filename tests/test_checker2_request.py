"""Request-header checks: fields, references, scope and routing rules."""

import datetime
import os
import pathlib
import subprocess
import tempfile
import unittest

from tools.checker2 import request

SHA40 = "a" * 40
HEADER = (
    "From: planner\n"
    "To: reviewer\n"
    "Sent: 2026-10-26T12:00:00Z\n"
    "Basic idea: rebuild the reader\n"
    "Task scope: reader\n"
)
CODER_HEADER = (
    "From: reviewer\n"
    "To: coder\n"
    "Sent: 2026-10-26T12:00:00Z\n"
    "Basic idea: rebuild the reader\n"
    "Task scope: reader\n"
)


BODY = "\nThe task.\n"


class HeaderTest(unittest.TestCase):
    def test_valid_review_request_passes(self):
        with tempfile.TemporaryDirectory() as root:
            (pathlib.Path(root) / "pkg").mkdir()
            (pathlib.Path(root) / "pkg" / "SHA256SUMS.txt").write_text("", encoding="utf-8")
            text = HEADER.replace("To: reviewer", "To: owner") + BODY
            self.assertEqual(request.check(text, pathlib.Path(root), root), [])

    def test_missing_field_unknown_party_same_party_scope_and_time(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(request.check("From: reviewer\n", pathlib.Path(root), root),
                             [f"missing field: {n}" for n in ("To", "Sent", "Basic idea", "Task scope")]
                             + ["task body: empty (nothing after the header block)"])
            bad_party = HEADER.replace("To: reviewer", "To: nobody")
            self.assertIn("From or To is not a known party", request.check(bad_party, pathlib.Path(root), root))
            same = HEADER.replace("To: reviewer", "To: planner")
            self.assertIn("From and To are the same party", request.check(same, pathlib.Path(root), root))
            scope = HEADER.replace("Task scope: reader", "Task scope: missing-item")
            self.assertIn("task scope item not in basic idea: missing-item",
                          request.check(scope, pathlib.Path(root), root))
            bad_time = HEADER.replace("2026-10-26T12:00:00Z", "tomorrow")
            self.assertIn("Sent: not an ISO time", request.check(bad_time, pathlib.Path(root), root))


class CoderTest(unittest.TestCase):
    def test_coder_needs_pre_code_fields_base_and_zero_open_choices(self):
        with tempfile.TemporaryDirectory() as root:
            reasons = request.check(CODER_HEADER, pathlib.Path(root), root)
            self.assertIn("missing pre-code field: Pre-code study", reasons)

    def test_open_choice_row_base_sha_and_round_two_sweep(self):
        with tempfile.TemporaryDirectory() as root:
            rootp = pathlib.Path(root)
            (rootp / "answers.md").write_text("| choice | answer |\n| c1 | later |\n", encoding="utf-8")
            (rootp / "study.md").write_text("x", encoding="utf-8")
            (rootp / "tests.md").write_text("x", encoding="utf-8")
            (rootp / "plan.md").write_text("x", encoding="utf-8")
            import hashlib
            sha = hashlib.sha256(b"x").hexdigest()
            size = 1
            head = CODER_HEADER + (
                f"Pre-code study: study.md sha256={sha} size={size}\n"
                "Test list: tests.md\n"
                "Answers: answers.md\n"
                "Plan: plan.md\n"
                "Base sha: " + "b" * 10 + "\n"
                "Open choices: 1\n"
                "Dependencies: none\n"
                "Allowed paths: tools/\n"
                "Round: 2\n"
            )
            reasons = request.check(head, rootp, root)
            self.assertIn("Base sha: not a full 40-character sha", reasons)
            self.assertIn("Answers: a choice row is still open (later, TBD, todo or ?)", reasons)
            self.assertIn("Open choices: must be 0 before coding", reasons)
            self.assertIn("Round 2 or more: same-class sweep table missing", reasons)

    def test_fix_rule_and_report_section_are_required(self):
        with tempfile.TemporaryDirectory() as root:
            rootp = pathlib.Path(root)
            (rootp / "report.md").write_text("no section here\n", encoding="utf-8")
            fix = CODER_HEADER + "Review notes: r1.md\nFix rule: wrong\n"
            self.assertIn("Fix rule: missing or not the exact rule text (a fix request after review notes)",
                          request.check(fix, rootp, root))
            report_head = HEADER.replace("From: planner", "From: coder") + "Report: report.md\n"
            self.assertIn("Report: missing section 'Choices not covered'",
                          request.check(report_head, rootp, root))


class ReferenceTest(unittest.TestCase):
    def test_sha_size_and_not_after_request(self):
        with tempfile.TemporaryDirectory() as root:
            rootp = pathlib.Path(root)
            (rootp / "study.md").write_text("abc", encoding="utf-8")
            self.assertEqual(request.ref_reason("study.md", rootp, "Pre-code study", None, pinned=False), None)
            self.assertEqual(request.ref_reason("missing.md", rootp, "Plan", None, pinned=False),
                             "Plan: file not found missing.md")
            self.assertEqual(request.ref_reason("study.md sha256=" + "0" * 64 + " size=3", rootp, "x", None, False),
                             "x: sha256 differs")
            self.assertEqual(request.ref_reason("study.md", rootp, "Pre-code study", None, pinned=True),
                             "Pre-code study: needs sha256 and size")
            early = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
            self.assertEqual(request.ref_reason("study.md", rootp, "Pre-code study", early, pinned=True),
                             "Pre-code study: needs sha256 and size")


class PackageAndDependencyTest(unittest.TestCase):
    def test_reviewer_package_needs_sums_and_scope(self):
        with tempfile.TemporaryDirectory() as root:
            rootp = pathlib.Path(root)
            pkg = rootp / "pkg"
            pkg.mkdir()
            head = {"Package": ["pkg"], "Allowed paths": ["tools/"]}
            self.assertEqual(request.package_reasons(head, rootp), ["Package: SHA256SUMS.txt missing in the folder"])
            (pkg / "SHA256SUMS.txt").write_text("", encoding="utf-8")
            (pkg / "p.diff").write_text("+++ b/src/out.py\n", encoding="utf-8")
            self.assertEqual(request.package_reasons(head, rootp), ["Allowed paths: outside scope src/out.py"])

    def test_dependency_must_be_an_ancestor_of_the_base(self):
        with tempfile.TemporaryDirectory() as repo:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.run(["git", "-C", repo, "init", "-q", "-b", "main"], check=True, env=env)
            subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "a"], check=True, env=env)
            base = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True,
                                  text=True, check=True).stdout.strip()
            self.assertTrue(request.is_ancestor(repo, base, base))
            self.assertFalse(request.is_ancestor(repo, "c" * 40, base))


class TruncatedRequestTest(unittest.TestCase):
    """A 9-line request to the reviewer with no "Main sha:" line and no body used to PASS."""

    FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "truncated-9-line-request.md"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        pkg = self.root / "exchange" / "packages" / "p01"
        pkg.mkdir(parents=True)
        (pkg / "SHA256SUMS.txt").write_text("", encoding="utf-8")
        self.text = self.FIXTURE.read_text(encoding="utf-8")

    def test_the_truncated_request_is_returned_naming_both_missing_parts(self):
        self.assertEqual(len(self.text.splitlines()), 9)
        self.assertEqual(request.check(self.text, self.root, self.root),
                         ["missing field: Main sha", "task body: empty (nothing after the header block)"])

    def test_with_main_sha_and_a_body_it_passes(self):
        full = self.text + "Main sha: " + SHA40 + "\n" + BODY
        self.assertEqual(request.check(full, self.root, self.root), [])

    def test_main_sha_must_be_one_full_sha(self):
        for extra, want in (("Main sha: abc\n", "Main sha: not a full 40-character sha"),
                            ("Main sha: " + SHA40 + "\nMain sha: " + SHA40 + "\n",
                             "Main sha: must appear on exactly one line, found 2")):
            with self.subTest(want=want):
                self.assertIn(want, request.check(self.text + extra + BODY, self.root, self.root))

    def test_main_sha_is_for_reviewer_requests_only(self):
        text = self.text.replace("To: reviewer", "To: owner") + BODY
        self.assertEqual(request.check(text, self.root, self.root), [])

    def test_gate_and_route_return_it(self):
        from tools.checker2 import request_gate, route
        self.assertEqual(request_gate.main([str(self.FIXTURE), "--root", str(self.root), "--repo", str(self.root)]), 1)
        self.assertEqual(route.send(self.FIXTURE, self.root, self.root), "RETURN")


if __name__ == "__main__":
    unittest.main()


class GateEntryTest(unittest.TestCase):
    def test_one_argument_exit_codes_match_the_old_checker(self):
        from tools.checker2 import request_gate
        with tempfile.TemporaryDirectory() as root:
            good = pathlib.Path(root) / "good.md"
            good.write_text(HEADER.replace("To: reviewer", "To: owner") + BODY, encoding="utf-8")
            bad = pathlib.Path(root) / "bad.md"
            bad.write_text("From: reviewer\n", encoding="utf-8")
            self.assertEqual(request_gate.main([str(good), "--root", root, "--repo", root]), 0)
            self.assertEqual(request_gate.main([str(bad), "--root", root, "--repo", root]), 1)


class SinglePackageLineTest(unittest.TestCase):
    def test_a_reviewer_request_needs_exactly_one_package_line(self):
        with tempfile.TemporaryDirectory() as root:
            rootp = pathlib.Path(root)
            pkg = rootp / "pkg"
            pkg.mkdir()
            (pkg / "SHA256SUMS.txt").write_text("", encoding="utf-8")
            base = "From: coder\nTo: reviewer\nSent: 2026-10-26T12:00:00Z\nBasic idea: x\nTask scope: x\n"
            once = base + "Package: pkg\n"
            twice = base + "Package: pkg\nPackage: pkg\n"
            self.assertFalse(any("exactly one line" in r for r in request.check(once, rootp, rootp)))
            self.assertIn("Package: must appear on exactly one line, found 2",
                          request.check(twice, rootp, rootp))
