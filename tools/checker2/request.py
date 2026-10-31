"""Request checks: header fields, references (sha256 and size), package scope, pre-code rules and the check.

Stateless: a pure function of the request text, the files it names, and git history.
"""

import datetime
import fnmatch
import hashlib
import re
import subprocess

PARTIES = {"planner", "runner", "coder", "reviewer", "owner"}
CODERS = {"coder"}
REVIEWERS = {"reviewer"}
REQUIRED = ("From", "To", "Sent", "Basic idea", "Task scope")
PRE_CODE = ("Pre-code study", "Test list", "Answers", "Plan", "Base sha", "Open choices", "Dependencies", "Allowed paths")
FIELD = re.compile(r"^([A-Za-z][A-Za-z -]*?):\s*(.*)$")
REF = re.compile(r"^(?P<path>\S+)(?: sha256=(?P<sha>[0-9a-f]{64}) size=(?P<size>\d+))?$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
FIX_RULE = "Run the failing review checks and sweep every place of the same class before delivery"
OPEN_ROW = re.compile(r"(?i)\|\s*(later|tbd|todo|\?)\s*\|")
# Every review request to the reviewer carries this standard text.
SINGLE_PASS_TEXT = ("Inventory every function and block first, give ALL findings in one pass, "
                    "and do not reopen a closed item without a new failure scenario.")
# The reviewer writes, for every finding, the defect, its root cause and its class.
ROOT_CAUSE_TEXT = "For every finding write three labelled lines: Defect:, Root cause:, Class:."
NO_FINDINGS_KINDS = ("run",)
COVERAGE_TEXT = ("Before the verdict, inventory every function in the fix.diff scope with a verdict for each. "
                 "For every finding, search the whole tree for every site of the same class and write the count on a "
                 "'Class sites: <n>' line, and write an 'Origin:' line (new in this round / reopened / on unchanged "
                 "lines: why it was not found earlier). Declare the review complete with the line 'coverage: COMPLETE'.")


def parse_header(text):
    """Return {field: [values]} for the header block (up to the first blank line)."""
    fields = {}
    key = None
    for line in text.splitlines():
        if not line.strip():
            break
        match = FIELD.match(line)
        if match:
            key = match.group(1)
            values = fields.setdefault(key, [])
            if match.group(2).strip():
                values.append(match.group(2).strip())
        elif line.startswith("- ") and key:
            fields[key].append(line[2:].strip())
    return fields


def parse_time(value):
    moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment


def ref_reason(value, root, label, sent, pinned):
    """Return a reason if a referenced file is missing, unpinned, changed or newer than the request."""
    match = REF.match(value)
    if not match:
        return f"{label}: bad reference {value!r}"
    if pinned and not match.group("sha"):
        return f"{label}: needs sha256 and size"
    path = root / match.group("path")
    if not path.is_file():
        return f"{label}: file not found {match.group('path')}"
    if match.group("sha") and hashlib.sha256(path.read_bytes()).hexdigest() != match.group("sha"):
        return f"{label}: sha256 differs"
    if match.group("size") and path.stat().st_size != int(match.group("size")):
        return f"{label}: size differs"
    if pinned and sent:
        modified = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
        if modified > sent:
            return f"{label}: dated after the request"
    return None


def ref_or_missing(head, name, root, sent, pinned):
    if not head.get(name):
        return [f"missing field: {name}"]
    reason = ref_reason(head[name][0], root, name, sent, pinned)
    return [reason] if reason else []


def package_reasons(head, root):
    """A review package is a folder that holds SHA256SUMS.txt; its patches must stay in Allowed paths."""
    if not head.get("Package"):
        return ["missing field: Package"]
    folder = root / head["Package"][0].replace("\\", "/")
    if not folder.is_dir():
        return [f"Package: folder not found {head['Package'][0]}"]
    if not (folder / "SHA256SUMS.txt").is_file():
        return ["Package: SHA256SUMS.txt missing in the folder"]
    scope = [item.lower() for item in head.get("Allowed paths", [])]
    for patch in sorted(folder.glob("*.diff")) + sorted(folder.glob("*.patch")):
        for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("+++ b/"):
                path = line[6:].strip().lower()
                if scope and not any(path.startswith(item) or fnmatch.fnmatchcase(path, item) for item in scope):
                    return [f"Allowed paths: outside scope {path}"]
    return []


def is_ancestor(repo, dep, base):
    try:
        result = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", dep, base],
                                capture_output=True, check=False)
    except OSError:
        return False
    return result.returncode == 0


def pre_code_reasons(head, root, sent, repo, text):
    missing = [f"missing pre-code field: {name}" for name in PRE_CODE if not head.get(name)]
    if missing:
        return missing
    reasons = ref_or_missing(head, "Pre-code study", root, sent, pinned=True)
    for name in ("Test list", "Answers", "Plan"):
        reasons += ref_or_missing(head, name, root, sent, pinned=False)
    base = head["Base sha"][0]
    if not SHA40.match(base):
        reasons.append("Base sha: not a full 40-character sha")
    answers = root / head["Answers"][0].split()[0]
    if answers.is_file() and any(line.startswith("|") and OPEN_ROW.search(line)
                                 for line in answers.read_text(encoding="utf-8").splitlines()):
        reasons.append("Answers: a choice row is still open (later, TBD, todo or ?)")
    if head["Open choices"][0] != "0":
        reasons.append("Open choices: must be 0 before coding")
    for dep in head["Dependencies"]:
        if dep.lower() == "none":
            continue
        if not SHA40.match(dep):
            reasons.append("Dependencies: each item must be 'none' or a 40-character sha")
        elif not is_ancestor(repo, dep, base):
            reasons.append(f"Dependencies: {dep} is not in the base")
    if head.get("Round") and head["Round"][0].isdigit() and int(head["Round"][0]) >= 2 \
            and "same-class sweep" not in text.lower():
        reasons.append("Round 2 or more: same-class sweep table missing")
    return reasons


def body_text(text):
    """The task body: everything after the header block's first blank line."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            return "\n".join(lines[index + 1:]).strip()
    return ""


def main_sha_reasons(text):
    """A request to the reviewer carries exactly one 'Main sha:' line with a full 40-character sha."""
    values = [line[len("Main sha:"):].strip() for line in text.splitlines() if line.startswith("Main sha:")]
    if not values:
        return ["missing field: Main sha"]
    if len(values) != 1:
        return [f"Main sha: must appear on exactly one line, found {len(values)}"]
    if not SHA40.match(values[0]):
        return ["Main sha: not a full 40-character sha"]
    return []


def text_present(text, sentence):
    """The exact standard sentence, whitespace and case folded, appears in the request."""
    return " ".join(sentence.split()).lower() in " ".join(text.split()).lower()


def single_pass_present(text):
    """(a) The exact single-pass sentence, whitespace and case folded, appears in the request."""
    return text_present(text, SINGLE_PASS_TEXT)


def review_return_problems(review_text):
    """A reviewer's REVIEW.md with findings: one 'Root cause:' line for each 'Defect:' line, each with text,
    and a 'Class:' line for each. A PASS return with no 'Defect:' line has nothing to check.
    """
    lines = [line.strip().lstrip("-*> ").replace("**", "") for line in review_text.splitlines()]
    def labelled(label):
        return [line[len(label):].strip() for line in lines if line.lower().startswith(label.lower())]
    defects, causes, classes = labelled("Defect:"), labelled("Root cause:"), labelled("Class:")
    head = " ".join(review_text.split()[:12]).upper()
    if not defects and "CHANGES_REQUIRED" in head:
        return ["review return: findings without 'Defect:' / 'Root cause:' / 'Class:' lines"]
    problems = []
    if re.search(r"(?im)^\W*(plan-)?verdict\s*:", review_text) and not re.search(r"(?im)^\W*coverage\s*:\s*COMPLETE\b",
                                                                              review_text):
        problems.append("review return: no 'coverage: COMPLETE' line; the reviewer must declare the review complete")
    sites = [c for c in labelled("Class sites:") if re.match(r"\d+", c)]
    if len(sites) < len(defects):
        problems.append(f"review return: {len(defects)} 'Defect:' line(s) but {len(sites)} 'Class sites: <n>' line(s)")
    origins = [o for o in labelled("Origin:") if o]
    if len(origins) < len(defects):
        problems.append(f"review return: {len(defects)} 'Defect:' line(s) but {len(origins)} 'Origin:' line(s); a "
                        "first finding on unchanged lines must say why it was not found earlier")
    if len(causes) < len(defects) or not all(causes):
        problems.append(f"review return: {len(defects)} 'Defect:' line(s) but {sum(1 for c in causes if c)} "
                        "'Root cause:' line(s) with text")
    if len(classes) < len(defects) or not all(classes):
        problems.append(f"review return: {len(defects)} 'Defect:' line(s) but {sum(1 for c in classes if c)} "
                        "'Class:' line(s) with text")
    return problems


CONFIRM_TEXT = ("Confirm pass: the earlier REVIEW(s) named on the 'Review notes:' line hold the findings so far. "
                "Review the same package again in full under the same rules, without a new suite run. If you find "
                "nothing beyond that list, write the line 'confirm: NO_NEW_FINDINGS' and repeat the full list; "
                "otherwise write 'confirm: NEW_FINDINGS' and give the full list with the new findings marked.")


def needs_confirm_pass(review_text):
    """A reviewer's findings do not go to the fixer until a confirm pass by the reviewer finds
    nothing new. True for a REVIEW with findings (Defect: lines, CHANGES_REQUIRED or a blocked plan verdict) that
    does not carry 'confirm: NO_NEW_FINDINGS'."""
    if re.search(r"(?im)^\W*confirm\s*:\s*NO_NEW_FINDINGS\b", review_text):
        return False
    head = " ".join(review_text.split()[:60]).upper()
    if any(word in head for word in ("CHANGES_REQUIRED", "PLAN_BLOCKED", "NEEDS_OWNER")):
        return True
    passed = re.search(r"(?im)^\W*(plan-)?verdict\s*:\s*(PASS|PLAN_READY)\b", review_text)
    # a passing verdict may still list Defect: lines for the findings it closed; those are not open findings
    return not passed and bool(re.search(r"(?im)^\W*defect\s*:", review_text))


# No full-suite run unless the review is clean; the suite run is the last step before the merge.
# A review request that also asks for the suite, or a run request without a clean review, is returned.
SUITE_RUN = re.compile(r"(?i)run_tests_parallel|unittest\s+discover|windows\s+(suite|run|gate)|full\s+(test\s+)?suite")


NEGATION = re.compile(r"(?i)\b(no|not|never|without)\b")


def suite_requested(text):
    """A suite command or phrase that is asked for; 'no full suite in this request' is not a request."""
    for match in SUITE_RUN.finditer(text):
        before = re.split(r"[.;:\n(]", text[max(0, match.start() - 40):match.start()])[-1]
        if not NEGATION.search(before):
            return True
    return False


def run_only_text(text):
    """The text of every 'Run only:' line (a field may sit outside the header block)."""
    return " ".join(m.group(1) for m in re.finditer(r"(?im)^Run only:\s*(.*)$", text))


def clean_review(review_text):
    """True when the review passed and holds no finding still waiting for a confirm pass."""
    passed = re.search(r"(?im)^\W*(plan-)?verdict\s*:\s*(PASS|PLAN_READY)\b", review_text)
    return bool(passed) and not needs_confirm_pass(review_text)


def windows_run_reasons(head, text, root, kind):
    """A review request may not ask for the suite; a suite request must name a clean review ('Clean review:')."""
    if kind not in NO_FINDINGS_KINDS:
        if suite_requested(run_only_text(text)):
            return [("review request asks for the full suite run; the suite is filed on its own, "
                     "only after a clean review (no new findings) and before the merge")]
        return []
    if not suite_requested(text):
        return []
    if not head.get("Clean review"):
        return ["suite run request: missing field 'Clean review:' (the passing REVIEW with no new findings)"]
    path = root / head["Clean review"][0].split()[0]
    if not path.is_file():
        return [f"Clean review: file not found: {head['Clean review'][0]}"]
    if not clean_review(path.read_text(encoding="utf-8", errors="replace")):
        return ["Clean review: the named REVIEW is not a clean pass (no PASS verdict, or findings still open)"]
    return []


def check(text, root, repo):
    """Return the list of reasons the request is returned; an empty list means PASS."""
    head = parse_header(text)
    missing = [f"missing field: {name}" for name in REQUIRED if not head.get(name)]
    reasons = list(missing)
    if head.get("To") and head["To"][0].lower() in REVIEWERS:
        reasons += main_sha_reasons(text)
    if not body_text(text):
        reasons.append("task body: empty (nothing after the header block)")
    if missing:
        return reasons
    sender = head["From"][0].lower()
    receiver = head["To"][0].lower()
    if sender not in PARTIES or receiver not in PARTIES:
        reasons.append("From or To is not a known party")
    if sender == receiver:
        reasons.append("From and To are the same party")
    basic = " ".join(head["Basic idea"]).lower()
    reasons += [f"task scope item not in basic idea: {item}" for item in head["Task scope"]
                if item.lower() not in basic]
    try:
        sent = parse_time(head["Sent"][0])
    except ValueError:
        return reasons + ["Sent: not an ISO time"]
    if receiver in CODERS:
        reasons += pre_code_reasons(head, root, sent, repo, text)
    if receiver in CODERS and head.get("Review notes") and " ".join(head.get("Fix rule", [])) != FIX_RULE:
        reasons.append("Fix rule: missing or not the exact rule text (a fix request after review notes)")
    if receiver in REVIEWERS and head.get("gate-kind") and not single_pass_present(text):
        reasons.append("review request: the standard single-pass text is missing: " + SINGLE_PASS_TEXT)
    kind = " ".join(head.get("gate-kind", [])).strip().lower()
    if receiver in REVIEWERS and kind and kind not in NO_FINDINGS_KINDS and not text_present(text, ROOT_CAUSE_TEXT):
        reasons.append("review request: the standard root-cause text is missing: " + ROOT_CAUSE_TEXT)
    if receiver in REVIEWERS and kind and kind not in NO_FINDINGS_KINDS and not text_present(text, COVERAGE_TEXT):
        reasons.append("review request: the standard full-coverage text is missing: " + COVERAGE_TEXT)
    if receiver in REVIEWERS:
        reasons += windows_run_reasons(head, text, root, kind)
    if receiver in REVIEWERS:
        count = sum(1 for line in text.splitlines() if line.startswith("Package:"))
        if count != 1:
            reasons.append(f"Package: must appear on exactly one line, found {count}")
        reasons += package_reasons(head, root)
    if sender in CODERS | REVIEWERS:
        reasons += ref_or_missing(head, "Report", root, None, pinned=False)
    if sender in CODERS and head.get("Report") and (root / head["Report"][0].split()[0]).is_file():
        report_text = (root / head["Report"][0].split()[0]).read_text(encoding="utf-8")
        if "choices not covered" not in report_text.lower():
            reasons.append("Report: missing section 'Choices not covered'")
    return reasons
