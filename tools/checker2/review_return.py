"""Check a reviewer's REVIEW.md before it is relayed: every finding carries Defect:, Root cause: and Class: lines.

Usage: python -m tools.checker2.review_return <REVIEW.md>
Exit 0 = PASS (relay to the fixer), 1 = RETURN (the reasons are printed), 3 = CONFIRM (well formed, but its
findings go back to the reviewer for a confirm pass with request.CONFIRM_TEXT until it answers
'confirm: NO_NEW_FINDINGS'; nothing goes to the fixer before that).
"""

import pathlib
import sys

from tools.checker2 import request


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    text = pathlib.Path(argv[0]).read_text(encoding="utf-8", errors="replace")
    problems = request.review_return_problems(text)
    if not problems and request.needs_confirm_pass(text):
        print("CONFIRM")
        print("- findings go back to the reviewer for a confirm pass: " + request.CONFIRM_TEXT)
        return 3
    print("RETURN" if problems else "PASS")
    for problem in problems:
        print("- " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
