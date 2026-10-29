"""Routing writer for a request runner: one request file in, PASS or RETURN out.

PASS: copies the request to exchange/outbox/<receiver>/<stamp>-<name> and writes
      <same name>.PASS.txt with 'PASS <stamp> sha256=<hash of the request bytes>'.
RETURN: writes exchange/returned/<sender>/<stamp>-<name>.RETURN.txt with the reasons.
Both: appends one audit line to exchange/audit.log.
Usage: python -m tools.checker2.route <request.md> [--root <project folder>] [--repo <git checkout>]
Exit 0 = PASS, 1 = RETURN.
"""

import argparse
import datetime
import hashlib
import pathlib
import shutil
import sys

from tools.checker2 import request

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO = ROOT


def send(path, root=ROOT, repo=REPO, now=None):
    """Check one request, route it, log it. Return 'PASS' or 'RETURN'."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    text = path.read_text(encoding="utf-8")
    head = request.parse_header(text)
    sender = head.get("From", ["unknown"])[0].lower()
    receiver = head.get("To", ["unknown"])[0].lower()
    reasons = request.check(text, root, repo)
    checker_dir = root / "exchange"
    if reasons:
        verdict = "RETURN"
        note = checker_dir / "returned" / sender / f"{stamp}-{path.name}.RETURN.txt"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("RETURNED to " + sender + "\n" + "".join(f"- {r}\n" for r in reasons), encoding="utf-8")
    else:
        verdict = "PASS"
        target = checker_dir / "outbox" / receiver / f"{stamp}-{path.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        target.with_name(target.name + ".PASS.txt").write_text(f"PASS {stamp} sha256={digest}\n", encoding="utf-8")
    checker_dir.mkdir(parents=True, exist_ok=True)
    with (checker_dir / "audit.log").open("a", encoding="utf-8") as log:
        log.write(f"{stamp} | {sender} -> {receiver} | {path.name} | {verdict} | {'; '.join(reasons)}\n")
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check one request, route it, log it.")
    parser.add_argument("request", type=pathlib.Path)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    parser.add_argument("--repo", type=pathlib.Path, default=REPO)
    args = parser.parse_args(argv)
    verdict = send(args.request, args.root, args.repo)
    print(verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
