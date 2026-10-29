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


def check(text, root, repo):
    """Return the list of reasons the request is returned; an empty list means PASS."""
    head = parse_header(text)
    reasons = [f"missing field: {name}" for name in REQUIRED if not head.get(name)]
    if reasons:
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
    if receiver in REVIEWERS:
        reasons += package_reasons(head, root)
    if sender in CODERS | REVIEWERS:
        reasons += ref_or_missing(head, "Report", root, None, pinned=False)
    if sender in CODERS and head.get("Report") and (root / head["Report"][0].split()[0]).is_file():
        report_text = (root / head["Report"][0].split()[0]).read_text(encoding="utf-8")
        if "choices not covered" not in report_text.lower():
            reasons.append("Report: missing section 'Choices not covered'")
    return reasons
