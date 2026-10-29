"""Single-request gate for a runner tick: one request file in, exit 0 PASS, 1 RETURN.

Usage: python -m tools.checker2.request_gate <request.md> [--root <project folder>] [--repo <git checkout>]
Prints PASS, or RETURN followed by one reason per line. Exit 0 = PASS, 1 = RETURN.
Defaults: root is the folder that holds tools/, repo is the same folder.
Stateless: it writes nothing (no outbox, no audit log).
"""

import argparse
import pathlib
import sys

from tools.checker2 import request

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO = ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check one request file.")
    parser.add_argument("request", type=pathlib.Path)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    parser.add_argument("--repo", type=pathlib.Path, default=REPO)
    args = parser.parse_args(argv)
    reasons = request.check(args.request.read_text(encoding="utf-8"), args.root, args.repo)
    if reasons:
        print("RETURN")
        for reason in reasons:
            print(f"- {reason}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
