"""Output guard: refuses a code output (a diff) that touches a path outside the task's allowed list.

Usage: python -m tools.checker2.output_guard <allowed-paths-file> <output.diff>
Exit 0 = every path in the diff is allowed; exit 1 = each refused path is printed as REFUSED <path>.
Keeps no state. An empty allowed list refuses every path.
"""

import pathlib
import sys

from tools.checker2 import core


def diff_paths(diff_text):
    """Every path a diff changes: new names ('+++ b/'), old names of deletions ('--- a/' before '+++ /dev/null'),
    and both names of a rename."""
    paths, old = [], None
    for line in diff_text.splitlines():
        if line.startswith("--- a/"):
            old = line[6:].strip()
        elif line.startswith("+++ b/"):
            paths.append(line[6:].strip())
        elif line.startswith("+++ /dev/null") and old:
            paths.append(old)
        elif line.startswith("rename from ") or line.startswith("rename to "):
            paths.append(line.split(" ", 2)[2].strip())
    return paths


def refused(diff_text, allowed):
    """Return the paths in the diff outside the allowed list."""
    return [path for path in diff_paths(diff_text) if core.out_of_scope("+++ b/" + path + "\n", allowed)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    allowed = [line.strip() for line in pathlib.Path(argv[0]).read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = refused(pathlib.Path(argv[1]).read_text(encoding="utf-8", errors="replace"), allowed)
    for path in bad:
        print("REFUSED " + path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
