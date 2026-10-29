"""Checks a task package before it goes to a reviewer. Stdlib only, no state kept between runs."""

import ctypes
import fnmatch
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
from ctypes import wintypes


def live_state(repo, expected_branch, lock_file, banned_commands_seen=()):
    """Return a list of problems. Empty list means the live state passes."""
    problems = []
    try:
        probe = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        probe = None
        problems.append(f"UNVERIFIED: git cannot run here ({exc}); branch not checked")
    if probe is not None and probe.returncode != 0:
        problems.append(f"UNVERIFIED: no git checkout at {repo} ({probe.stderr.strip()[:120]}); branch not checked")
    elif probe is not None and probe.stdout.strip() != expected_branch:
        problems.append(f"branch is {probe.stdout.strip()!r}, expected {expected_branch!r}")
    lock = pathlib.Path(lock_file)
    if lock.exists():
        holder = lock_holder_state(lock)
        problems.append(f"lock held by a live job: {lock_file}" if holder == "live" else f"stale lock: {lock_file}")
    problems.extend(f"banned command seen: {c}" for c in banned_commands_seen)
    return problems


def pid_running(pid):
    """Linux path and Windows path (GetExitCodeProcess) for one pid."""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def lock_holder_state(lock):
    """'live' if the pid written in the lock still runs, 'stale' otherwise (no pid counts as stale)."""
    try:
        match = re.search(r"pid=(\d+)", lock.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return "stale"
    if match and pid_running(int(match.group(1))):
        return "live"
    return "stale"


def seal(package_dir, task_id, round_no, base, out_name="SEAL.json"):
    """Hash every file in the package (except the seal) and write the seal next to it."""
    root = pathlib.Path(package_dir)
    digests = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != out_name):
        digests[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    body = {"task_id": task_id, "round": round_no, "base": base, "files": digests}
    (root / out_name).write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    return body


def check_seal(package_dir, out_name="SEAL.json"):
    """Return the paths whose bytes differ from the seal, or are missing or new."""
    root = pathlib.Path(package_dir)
    sealed = json.loads((root / out_name).read_text(encoding="utf-8"))["files"]
    now = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file() and p.name != out_name
    }
    return sorted(k for k in set(sealed) | set(now) if sealed.get(k) != now.get(k))


def reply_check(sites, rows):
    """Each site named by the core list needs one answered row. Open rows are refused."""
    problems = []
    answered = {r["site"]: r for r in rows}
    for site in sites:
        row = answered.get(site)
        if row is None:
            problems.append(f"no row for site {site}")
        elif not str(row.get("answer", "")).strip():
            problems.append(f"open row for site {site}")
    return problems


def out_of_scope(patch_text, allowed):
    """Return the first changed path outside the allowed prefixes or globs, or None.

    Same rule as package_reasons in request.py: lowercase paths,
    a path must start with an allowed item or match it as a glob).
    """
    scope = [item.lower() for item in allowed]
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip().lower()
            if scope and not any(path.startswith(item) or fnmatch.fnmatchcase(path, item) for item in scope):
                return path
    return None


def gate_passes(check, expect, cwd):
    """Run one runnable condition (CHECK/EXPECT). Pass only if exit 0 and EXPECT appears in the output.

    A runnable condition: a command must exit 0 and print the expected text.
    """
    result = subprocess.run(shlex.split(check), cwd=cwd, capture_output=True, text=True, check=False)
    return result.returncode == 0 and expect in (result.stdout + result.stderr)


def job_abandoned(log_text, task_id):
    """True if the runner log's last line for this task is a start line (no end line): the job stopped unfinished.

    An unfinished job counts as FAILED and must hand off; it never counts as passed.
    """
    last = None
    for line in log_text.splitlines():
        if task_id in line:
            last = line
    return last is not None and " start " in f" {last} "


def merge_problems(repo, expected_branch, lock_file, package_dir, out_name="SEAL.json"):
    """Re-check before a merge: live state again, and the seal still matches the package bytes.

    Any change since sealing voids the seal, so the list is non-empty and the merge is refused.
    """
    problems = live_state(repo, expected_branch, lock_file)
    problems.extend(f"seal voided by change: {name}" for name in check_seal(package_dir, out_name))
    return problems


def unlisted_hits(pattern, texts, sites):
    """Class sweep (v2 5.1): every line matching pattern must be a site the owner listed.

    texts: {path: text}; sites: set of 'path:line' strings. Return the unlisted 'path:line' hits.
    """
    hits = []
    for path in sorted(texts):
        for number, line in enumerate(texts[path].splitlines(), start=1):
            if re.search(pattern, line) and f"{path}:{number}" not in sites:
                hits.append(f"{path}:{number}")
    return hits
