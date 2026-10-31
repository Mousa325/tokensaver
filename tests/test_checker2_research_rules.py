import io
import pathlib
import tempfile
import unittest
import unittest.mock
import zipfile

from tools.checker2 import package_check, request, review_return

HEADER = ("From: runner\nTo: reviewer\nSent: 2026-10-29T21:00:00Z\nBasic idea: review x\nTask scope: review x\n"
          "gate-kind: review\nMain sha: " + "a" * 40 + "\nPackage: pkg\n\n")
SWEEP = ("| Finding | Finding class | Sites checked | Root cause fixed |\n|---|---|---|---|\n"
         "| R1-M01 | claim stronger than the code | tests/t.py:10-90, src/a.py:4 | cause: claims written before the code was read; src/a.py:4 |\n\nClass-walk test: logs/12-coverage.log\n")


def brief(round_no, body):
    return f"From: planner\nTo: coder\nRound: {round_no}\n\n" + body


class SinglePassTest(unittest.TestCase):
    def reasons(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            return request.check(text, pathlib.Path(tmp), tmp)

    def test_a_review_request_without_the_standard_text_is_returned(self):
        reasons = self.reasons(HEADER + "Do the review.\n")
        self.assertTrue(any("standard single-pass text is missing" in r for r in reasons), reasons)

    def test_the_standard_text_clears_that_reason_whatever_the_spacing_and_case(self):
        text = HEADER + "inventory every function   and block first, GIVE all findings in one pass, " \
            "and do not reopen a closed item without a new failure scenario.\n"
        self.assertFalse(any("single-pass" in r for r in self.reasons(text)))
        self.assertTrue(request.single_pass_present(request.SINGLE_PASS_TEXT))

    def test_a_request_without_gate_kind_is_not_asked_for_it(self):
        text = HEADER.replace("gate-kind: review\n", "") + "Do the review.\n"
        self.assertFalse(any("single-pass" in r for r in self.reasons(text)))


class VariantSweepTest(unittest.TestCase):
    def test_round_one_and_no_round_are_not_checked(self):
        self.assertEqual(package_check.variant_sweep_problems(brief(1, "nothing")), [])
        self.assertEqual(package_check.variant_sweep_problems("no round field"), [])

    def test_a_round_two_brief_with_table_and_class_walk_passes(self):
        self.assertEqual(package_check.variant_sweep_problems(brief(2, SWEEP)), [])

    def test_missing_table_missing_class_walk_and_empty_cells_are_reported(self):
        self.assertTrue(any("table" in p for p in package_check.variant_sweep_problems(brief(3, "text"))))
        no_walk = SWEEP.split("\nClass-walk")[0]
        self.assertTrue(any("Class-walk" in p for p in package_check.variant_sweep_problems(brief(2, no_walk))))
        empty = SWEEP.replace("tests/t.py:10-90, src/a.py:4", "everything")
        self.assertTrue(any("needs a class and the sites" in p for p in package_check.variant_sweep_problems(brief(2, empty))))

    def test_a_reopened_finding_is_one_item(self):
        twice = SWEEP.replace("\n\nClass-walk", "\n| r1-m01 | same | tests/t.py:5, src/b.py:2 | cause: same root; src/b.py:2 x |\n\nClass-walk")
        problems = package_check.variant_sweep_problems(brief(2, twice))
        self.assertTrue(any("appears twice" in p for p in problems), problems)

    def test_rows_of_a_later_table_are_not_read_as_sweep_rows(self):
        later = SWEEP.replace("\n\nClass-walk", "\n\n| Rule | File | Result |\n|---|---|---|\n| W1 | a.py | OK |\n\nClass-walk")
        self.assertEqual(package_check.variant_sweep_problems(brief(2, later)), [])

    def test_a_row_with_one_site_and_no_reason_is_refused(self):
        one = SWEEP.replace("tests/t.py:10-90, src/a.py:4", "tests/t.py:10-90")
        problems = package_check.variant_sweep_problems(brief(2, one))
        self.assertTrue(any("names one site" in p for p in problems), problems)

    def test_the_same_site_twice_is_still_one_site(self):
        same = SWEEP.replace("tests/t.py:10-90, src/a.py:4", "tests/t.py:10-90 and tests/t.py:10-90")
        self.assertTrue(any("names one site" in p for p in package_check.variant_sweep_problems(brief(2, same))))

    def test_one_site_with_a_written_reason_passes(self):
        reason = SWEEP.replace("tests/t.py:10-90, src/a.py:4", "tests/t.py:10-90; only site: grep of the class finds no other")
        self.assertEqual(package_check.variant_sweep_problems(brief(2, reason)), [])
        empty_reason = SWEEP.replace("tests/t.py:10-90, src/a.py:4", "tests/t.py:10-90; only site:")
        self.assertTrue(package_check.variant_sweep_problems(brief(2, empty_reason)))

    def test_a_row_without_the_root_cause_fix_is_refused(self):
        fixed = "cause: claims written before the code was read; src/a.py:4"
        for cell in ("", "patched the test", "src/a.py:4", "cause: x; src/a.py:4", "cause: the root cause in words"):
            text = SWEEP.replace(f"| {fixed} |\n", f"| {cell} |\n")
            problems = package_check.variant_sweep_problems(brief(2, text))
            self.assertTrue(any("root cause" in p for p in problems), (cell, problems))
        three_columns = SWEEP.replace(" Root cause fixed |", "").replace("|---|---|---|---|", "|---|---|---|")
        self.assertTrue(any("table" in p for p in package_check.variant_sweep_problems(brief(2, three_columns))))

    def test_two_class_walk_lines_are_refused(self):
        self.assertTrue(package_check.variant_sweep_problems(brief(2, SWEEP + "Class-walk test: another.log\n")))


class ClassWalkInChangeTest(unittest.TestCase):
    WALK = SWEEP.replace("logs/12-coverage.log", "tests/test_walk.py::Walk")

    def test_the_named_test_must_be_a_changed_file(self):
        self.assertEqual(package_check.class_walk_problems(brief(2, self.WALK), ["src/a.py", "tests/test_walk.py"]), [])
        problems = package_check.class_walk_problems(brief(2, self.WALK), ["src/a.py", "tests/test_other.py"])
        self.assertTrue(any("not a changed file" in p for p in problems), problems)

    def test_an_old_log_is_not_a_class_test_of_the_change(self):
        self.assertTrue(package_check.class_walk_problems(brief(2, SWEEP), ["src/a.py", "tests/test_walk.py"]))

    def test_a_bare_file_name_matches_its_changed_path(self):
        bare = SWEEP.replace("logs/12-coverage.log", "test_walk.py")
        self.assertEqual(package_check.class_walk_problems(brief(2, bare), ["tests/test_walk.py"]), [])

    def test_round_one_paper_and_missing_line_are_not_checked_here(self):
        self.assertEqual(package_check.class_walk_problems(brief(1, self.WALK), ["src/a.py"]), [])
        self.assertEqual(package_check.class_walk_problems(brief(2, self.WALK), []), [])
        no_walk = self.WALK.split("\nClass-walk")[0]
        self.assertEqual(package_check.class_walk_problems(brief(2, no_walk), ["src/a.py"]), [])


class RootCauseTest(unittest.TestCase):
    def reasons(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            return request.check(text, pathlib.Path(tmp), tmp)

    def test_a_review_request_must_ask_for_defect_root_cause_and_class(self):
        body = request.SINGLE_PASS_TEXT + "\n"
        self.assertTrue(any("root-cause text is missing" in r for r in self.reasons(HEADER + body)))
        self.assertFalse(any("root-cause" in r for r in self.reasons(HEADER + body + request.ROOT_CAUSE_TEXT + "\n")))

    def test_a_run_only_request_is_not_asked_for_it(self):
        run = HEADER.replace("gate-kind: review", "gate-kind: run") + request.SINGLE_PASS_TEXT + "\n"
        self.assertFalse(any("root-cause" in r for r in self.reasons(run)))

    def test_a_return_with_each_finding_labelled_passes(self):
        text = ("verdict: CHANGES_REQUIRED\ncoverage: COMPLETE\n### R6-01\n- **Defect:** x leaks\n"
                "- **Root cause:** check after use\n- **Class:** check-then-use\n- **Class sites:** 4\n"
                "- **Origin:** unchanged lines; the earlier round read only the changed hunk\n")
        self.assertEqual(request.review_return_problems(text), [])
        self.assertEqual(request.review_return_problems("verdict: PASS\ncoverage: COMPLETE\nno findings\n"), [])

    def test_a_finding_without_its_root_cause_or_class_is_returned(self):
        text = ("verdict: CHANGES_REQUIRED\ncoverage: COMPLETE\nDefect: a\nRoot cause: b\nClass: c\nClass sites: 1\n"
                "Origin: new\nDefect: d\nRoot cause:\nClass sites: 2\nOrigin: new\n")
        problems = request.review_return_problems(text)
        self.assertTrue(any("Root cause" in p for p in problems) and any("Class" in p for p in problems), problems)
        self.assertTrue(request.review_return_problems("verdict: CHANGES_REQUIRED\n| R1 | High | x |\n"))
        self.assertEqual(request.review_return_problems("run-verdict: RED\nfailures 7\n"), [])


class FullCoverageTest(unittest.TestCase):
    # every review inventories each function, counts each class over the whole tree,
    # declares the review complete, and explains a first finding on unchanged lines
    def reasons(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            return request.check(text, pathlib.Path(tmp), tmp)

    def test_a_review_request_without_the_full_coverage_text_is_returned(self):
        body = request.SINGLE_PASS_TEXT + "\n" + request.ROOT_CAUSE_TEXT + "\n"
        self.assertTrue(any("full-coverage text is missing" in r for r in self.reasons(HEADER + body)))
        self.assertFalse(any("full-coverage" in r for r in self.reasons(HEADER + body + request.COVERAGE_TEXT + "\n")))
        run = HEADER.replace("gate-kind: review", "gate-kind: run") + body
        self.assertFalse(any("full-coverage" in r for r in self.reasons(run)))

    def test_a_return_without_the_completeness_line_is_returned(self):
        problems = request.review_return_problems("plan-verdict: PLAN_READY\nall fine\n")
        self.assertTrue(any("coverage: COMPLETE" in p for p in problems), problems)

    def test_a_finding_without_its_class_count_or_origin_is_returned(self):
        text = ("verdict: CHANGES_REQUIRED\ncoverage: COMPLETE\nDefect: a\nRoot cause: b\nClass: c\n"
                "Class sites: many\n")
        problems = request.review_return_problems(text)
        self.assertTrue(any("Class sites: <n>" in p for p in problems), problems)
        self.assertTrue(any("Origin:" in p for p in problems), problems)


class ConfirmPassTest(unittest.TestCase):
    # findings go back to the reviewer until a pass with no new findings; only then to the fixer
    FOUND = ("verdict: CHANGES_REQUIRED\ncoverage: COMPLETE\nDefect: a\nRoot cause: b\nClass: c\nClass sites: 2\n"
             "Origin: new in this round\n")

    def code(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "REVIEW.md"
            path.write_text(text, encoding="utf-8")
            with unittest.mock.patch("builtins.print"):
                return review_return.main([str(path)])

    def test_a_first_review_with_findings_goes_back_for_a_confirm_pass(self):
        self.assertTrue(request.needs_confirm_pass(self.FOUND))
        self.assertEqual(self.code(self.FOUND), 3)

    def test_a_confirm_pass_with_new_findings_goes_back_again(self):
        again = self.FOUND.replace("coverage: COMPLETE", "coverage: COMPLETE\nconfirm: NEW_FINDINGS")
        self.assertEqual(self.code(again), 3)

    def test_a_confirm_pass_with_nothing_new_goes_to_the_fixer(self):
        done = self.FOUND.replace("coverage: COMPLETE", "coverage: COMPLETE\nconfirm: NO_NEW_FINDINGS")
        self.assertFalse(request.needs_confirm_pass(done))
        self.assertEqual(self.code(done), 0)

    def test_a_ready_verdict_listing_closed_findings_goes_to_the_fixer(self):
        # PLAN_READY with Defect: lines that describe the findings it closed
        ready = ("plan-verdict: PLAN_READY\ncoverage: COMPLETE\nP2-01: CLOSED\nDefect: earlier A deleted a build file\n"
                 "Root cause: r\nClass: c\nClass sites: 1\nOrigin: closed by the round-2 answers\n")
        self.assertFalse(request.needs_confirm_pass(ready))
        self.assertEqual(self.code(ready), 0)

    def test_a_clean_pass_and_a_malformed_return_keep_their_codes(self):
        self.assertEqual(self.code("verdict: PASS\ncoverage: COMPLETE\nno findings\n"), 0)
        self.assertEqual(self.code("verdict: CHANGES_REQUIRED\n| R1 | High | x |\n"), 1)


class RootMatchTest(unittest.TestCase):
    REVIEW = ("verdict: CHANGES_REQUIRED\n### R1-M01 — High — x\n- **Defect:** claim wrong\n"
              "- **Root cause:** claims written before the code was read\n- **Class:** overclaim\n")

    def test_the_fix_row_names_the_reviewers_root(self):
        self.assertEqual(package_check.reviewer_roots(self.REVIEW), {"R1-M01": "claims written before the code was read"})
        self.assertEqual(package_check.root_match_problems(brief(2, SWEEP), [self.REVIEW]), [])

    def test_a_row_naming_another_cause_is_refused(self):
        other = SWEEP.replace("cause: claims written before the code was read", "cause: typo in the test name here")
        problems = package_check.root_match_problems(brief(2, other), [self.REVIEW])
        self.assertTrue(any("does not name the reviewer's root" in p for p in problems), problems)

    def test_a_reviewed_finding_without_a_row_is_refused(self):
        review = self.REVIEW + "### R1-M02 — Medium — y\nDefect: d\nRoot cause: shared state\nClass: c\n"
        problems = package_check.root_match_problems(brief(2, SWEEP), [review])
        self.assertTrue(any("R1-M02" in p and "no row" in p for p in problems), problems)

    def test_round_one_without_a_review_and_old_reviews_are_not_matched(self):
        self.assertEqual(package_check.root_match_problems(brief(1, SWEEP), []), [])
        self.assertEqual(package_check.root_match_problems(brief(2, SWEEP), ["### R1-M01 x\nno labels\n"]), [])

    def test_a_round_one_label_does_not_skip_the_fix_of_a_reviewed_package(self):
        # a rebase renamed the task to Round: 1 while it fixed reviewed findings
        other = SWEEP.replace("cause: claims written before the code was read", "cause: typo in the test name here")
        self.assertTrue(package_check.variant_sweep_applies(brief(1, other), [self.REVIEW]))
        self.assertTrue(package_check.root_match_problems(brief(1, other), [self.REVIEW]))
        self.assertTrue(package_check.variant_sweep_problems(brief(1, "no table\n"), [self.REVIEW]))


def base_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


class ClassSearchTest(unittest.TestCase):
    REVIEW = ("verdict: CHANGES_REQUIRED\nR0-01/02 NOT_CLOSED\n### R1-M01 — High — x\nDefect: d\n"
              "Root cause: claims written before the code was read\nClass: overclaim\n")
    BASE = base_zip({"src/a.py": "x = open(p)\ny = 1\n", "tests/t.py": "open(q)\n", "docs/n.md": "open(r)\n",
                     "src/blob.bin": "open(\0)"})

    def search(self, rows):
        open_rows = "".join(f"| {f} | same class | src/a.py:2, only site: one assignment | cause: shared default read twice; src/a.py:2 |\n"
                            for f in ("R0-01", "R0-02"))
        return SWEEP.replace("\n\nClass-walk", "\n" + open_rows + "\nClass-walk") + "\n| Finding | Kind | Search | Paths | Hits |\n|---|---|---|---|---|\n" + rows

    def rows(self, r1="| R1-M01 | similar | `open\\(` | src/, tests/ | 2 |\n"):
        dependents = "".join(f"| {f} | dependents | `^y` | src/ | 1 |\n" for f in ("R1-M01", "R0-01", "R0-02"))
        return r1 + "| R0-01 | similar | `y = 1` | src/ | 1 |\n| R0-02 | similar | `y = 1` | src/ | 1 |\n" + dependents

    def test_short_form_not_closed_ids_are_open(self):
        self.assertEqual(package_check.open_findings([self.REVIEW]), {"R1-M01", "R0-01", "R0-02"})

    def test_a_search_matching_the_base_tree_and_covered_sites_passes(self):
        self.assertEqual(package_check.class_search_problems(brief(2, self.search(self.rows())), [self.REVIEW],
                                                             self.BASE), [])

    def test_a_missing_table_and_a_missing_open_finding_are_refused(self):
        problems = package_check.class_search_problems(brief(2, SWEEP), [self.REVIEW], self.BASE)
        self.assertTrue(any("table" in p and "missing" in p for p in problems), problems)
        problems = package_check.class_search_problems(
            brief(2, self.search("| R1-M01 | similar | `open\\(` | src/, tests/ | 2 |\n")), [self.REVIEW], self.BASE)
        self.assertTrue(any("R0-01" in p and "no 'similar' search row" in p for p in problems), problems)
        self.assertTrue(any("R1-M01" in p and "no 'dependents' search row" in p for p in problems), problems)

    def test_a_wrong_hit_count_is_refused(self):
        problems = package_check.class_search_problems(
            brief(2, self.search(self.rows("| R1-M01 | similar | `open\\(` | src/, tests/ | 5 |\n"))), [self.REVIEW], self.BASE)
        self.assertTrue(any("says 5 hits" in p and "have 2" in p for p in problems), problems)

    def test_a_hit_file_missing_from_sites_checked_is_refused(self):
        problems = package_check.class_search_problems(
            brief(2, self.search(self.rows("| R1-M01 | similar | `open\\(` | src/, tests/, docs/ | 3 |\n"))), [self.REVIEW],
            self.BASE)
        self.assertTrue(any("docs/n.md" in p and "not in its Sites checked" in p for p in problems), problems)

    def test_a_search_that_finds_nothing_or_does_not_compile_is_refused(self):
        problems = package_check.class_search_problems(
            brief(2, self.search(self.rows("| R1-M01 | similar | `nothing_here` | src/ | 0 |\n"))), [self.REVIEW], self.BASE)
        self.assertTrue(any("finds nothing" in p for p in problems), problems)
        problems = package_check.class_search_problems(
            brief(2, self.search(self.rows("| R1-M01 | similar | `open(` | src/ | 1 |\n"))), [self.REVIEW], self.BASE)
        self.assertTrue(any("does not compile" in p for p in problems), problems)

    def test_package_code_and_new_files_are_searched_but_prose_is_not(self):
        # evidence generators in refs/ and files a patch creates are outside base.zip
        patch = (b"diff --git a/tools/new.py b/tools/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/tools/new.py\n"
                 b"@@ -0,0 +1 @@\n+open(z)\ndiff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n+open(w)\n")
        package = {"refs/gen.py": b"open(g)\n", "task.md": b"open( in the brief\n", "fix.diff": patch}
        self.assertEqual(set(package_check.package_texts(package)), {"refs/gen.py", "tools/new.py"})
        problems = package_check.class_search_problems(
            brief(2, self.search(self.rows("| R1-M01 | similar | `open\\(` | src/, tests/, refs/, tools/ | 4 |\n"))),
            [self.REVIEW], self.BASE, package)
        self.assertTrue(any("refs/gen.py" in p and "tools/new.py" in p for p in problems), problems)
        covered = self.search(self.rows("| R1-M01 | similar | `open\\(` | src/, tests/, refs/, tools/ | 4 |\n")).replace(
            "tests/t.py:10-90, src/a.py:4", "tests/t.py:10-90, src/a.py:4, refs/gen.py:1, tools/new.py:1")
        self.assertEqual(package_check.class_search_problems(brief(2, covered), [self.REVIEW], self.BASE, package), [])

    def test_no_base_zip_is_refused_and_a_first_round_without_review_is_not_checked(self):
        problems = package_check.class_search_problems(brief(2, self.search(self.rows())), [self.REVIEW], None)
        self.assertTrue(any("base.zip" in p for p in problems), problems)
        self.assertEqual(package_check.class_search_problems(brief(1, "plain brief\n"), [], None), [])


if __name__ == "__main__":
    unittest.main()


class SuiteAfterCleanReviewTest(unittest.TestCase):
    # no full-suite run unless the review is clean; a wrong one is returned
    HEAD = ("From: runner\nTo: reviewer\nSent: 2026-10-30T23:50:00Z\nBasic idea: x\nTask scope: x\ngate-kind: {kind}\n"
            "{extra}\nbody\nRun only: {run}\n")

    def reasons(self, kind, run, extra="", review=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            if review is not None:
                (root / "REVIEW.md").write_text(review, encoding="utf-8")
            text = self.HEAD.format(kind=kind, run=run, extra=extra)
            return request.windows_run_reasons(request.parse_header(text), text, root, kind)

    def test_a_review_that_also_asks_for_the_suite_is_returned(self):
        run = r"PYTHON -B tools\run_tests_parallel.py --tests tests --jobs 8"
        self.assertTrue(self.reasons("code", run))
        self.assertTrue(self.reasons("", "the full suite on Windows"))

    def test_a_review_with_probes_only_passes(self):
        self.assertEqual(self.reasons("code", "none; targeted probes only"), [])

    def test_saying_no_suite_is_not_asking_for_it(self):
        run = "the targeted unittest modules of task.md section 5. NO Windows suite in this request (a separate run follows)."
        self.assertEqual(self.reasons("write", run), [])
        self.assertTrue(self.reasons("write", "targeted modules; then the Windows suite"))

    def test_a_suite_run_without_a_clean_review_is_returned(self):
        self.assertTrue(self.reasons("run", "tools/run_tests_parallel.py"))
        self.assertTrue(self.reasons("run", "tools/run_tests_parallel.py", "Clean review: missing.md"))

    def test_a_suite_run_after_a_review_with_open_findings_is_returned(self):
        open_findings = "verdict: CHANGES_REQUIRED\nDefect: a\n"
        self.assertTrue(self.reasons("run", "tools/run_tests_parallel.py", "Clean review: REVIEW.md", open_findings))

    def test_a_suite_run_after_a_clean_review_passes(self):
        clean = "verdict: PASS\ncoverage: COMPLETE\nconfirm: NO_NEW_FINDINGS\n"
        self.assertEqual(self.reasons("run", "tools/run_tests_parallel.py", "Clean review: REVIEW.md", clean), [])

    def test_a_run_request_that_is_not_the_suite_needs_no_review(self):
        self.assertEqual(self.reasons("run", "tools/smoke_check.cmd"), [])
