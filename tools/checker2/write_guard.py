"""Write guard: refuses changed paths that are outside the task's allowed list.

Run it before saving a change, or as a pre-commit hook:
    python -m tools.checker2.write_guard <allowed-paths-file> <changed path> [<changed path> ...]
Exit 0 = every path is allowed; exit 1 = the listed paths are printed as refused. Keeps no state.
"""

import pathlib
import sys

from tools.checker2 import core


def refused(paths, allowed):
    """Return the changed paths outside the allowed list (an empty list refuses every path)."""
    bad = []
    for path in paths:
        if core.out_of_scope("+++ b/" + path.replace("\\", "/") + "\n", allowed):
            bad.append(path)
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(__doc__)
        return 2
    allowed = [line.strip() for line in pathlib.Path(argv[0]).read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = refused(argv[1:], allowed)
    for path in bad:
        print("REFUSED " + path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
