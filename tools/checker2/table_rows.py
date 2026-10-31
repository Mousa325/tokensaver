"""Table rows of a brief/paper: only quoted code and literal descriptions.

A table whose header starts '| Covers |' has six columns: Covers | Class | Quoted code | What the quoted lines do |
Assertion | Decision. The third header cell names the sources: 'T = <path>, P = <path>' (paths relative to the
policy repo). Every row is checked against those files:

  A  a cited line number beyond its file;
  Q  a quoted entry `X:N  code` that is not exactly the stripped source line N;
  B  a backtick fragment in the description that is not verbatim in a source (dotted names: every part exists);
  D  a number in the description that occurs in none of the row's quoted lines;
  G  an overclaim word in Class / description / Decision (always, never, must, only, margin, guarantee, ...);
  H  an Assertion entry that is not an assert/self.fail line;
  R  a row without quoted code, a wrong column count, or a Decision outside OK/KEPT/FIXED/EXCLUDED/n.a.;
  C  with a grep log: a grep line number inside no Covers range and not in the brief's 'name-only lines:' note.
"""

import re

BANNED = [r"always", r"never", r"at most", r"at least", r"turns? into", r"guarantee\w*", r"ensure\w*", r"must",
          r"cannot", r"can't", r"only", r"by construction", r"margins?", r"slack", r"safe\w*", r"enough",
          r"nominal\w*", r"would", r"will", r"far", r"expected", r"stretch\w*", r"proves?", r"impossible",
          r"certain\w*", r"necessar\w*", r"mathematical\w*", r"deterministic\w*", r"cost\w*", r"late", r"later",
          r"too", r"sufficient", r"robust", r"reliabl\w*", r"fast", r"slow", r"flak\w*", r"race",
          r"no assertion rests"]
BAN_RE = re.compile(r"(?<![\w])(?:" + "|".join(BANNED) + r")(?![\w])", re.IGNORECASE)
DECISIONS = {"OK", "KEPT", "FIXED", "EXCLUDED", "n.a."}
ENTRY = re.compile(r"`([A-Z]):(\d+)  ([^`]*)`")
DOTTED = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*")
HEADER = "| Covers |"


def _norm(text):
    return re.sub(r"\s+", "", text.replace('"', "'"))


def split_row(line):
    """Split a markdown row on unescaped pipes; '\\|' is a literal pipe."""
    body = line.strip()[1:-1]
    cells, cur, i = [], "", 0
    while i < len(body):
        if body[i] == "\\" and body[i + 1:i + 2] == "|":
            cur += "|"
            i += 2
        elif body[i] == "|":
            cells.append(cur.strip())
            cur = ""
            i += 1
        else:
            cur += body[i]
            i += 1
    cells.append(cur.strip())
    return cells


def find_table(text):
    """Return (header cells, data row lines) of the first table whose header starts '| Covers |', else None."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(HEADER):
            rows = []
            for row in lines[index + 2:]:
                if not row.startswith("| "):
                    break
                rows.append(row)
            return split_row(line), rows
    return None


def source_map(header_cell):
    """'... T = a/b.py, P = c/d.py)' -> {'T': 'a/b.py', 'P': 'c/d.py'}"""
    return {k: v for k, v in re.findall(r"\b([A-Z]) = ([\w./-]+)", header_cell)}


def check(text, sources, grep_text=None):
    """sources: {letter: list of source lines}. Return (row count, failures); (0, []) when the text has no table."""
    found = find_table(text)
    if found is None:
        return 0, []
    header, rows = found
    fails = []
    if len(header) != 6:
        return len(rows), [f"table header has {len(header)} columns, expected 6"]
    pool_text = "\n".join("\n".join(lines) for lines in sources.values())
    normed = {k: _norm("\n".join(v)) for k, v in sources.items()}
    covered = set()

    def src_line(letter, number):
        lines = sources.get(letter)
        if lines is None:
            return None
        return lines[number - 1].strip() if 1 <= number <= len(lines) else None

    for ri, row in enumerate(rows, 1):
        cells = split_row(row)
        tag = f"row {ri} [{cells[0][:40]}]"
        if len(cells) != 6:
            fails.append(f"{tag}: R {len(cells)} columns, expected 6")
            continue
        covers, cls, quoted, does, asserts, decision = cells
        for m in re.finditer(r":(\d+)(?:-:(\d+))?", covers):
            first, last = int(m.group(1)), int(m.group(2) or m.group(1))
            covered.update(range(first, last + 1))
            limit = len(sources.get("T", []))
            if limit and last > limit:
                fails.append(f"{tag}: A covers :{last} beyond the test file ({limit} lines)")
        quotes = []
        entries = ENTRY.findall(quoted)
        if not entries:
            fails.append(f"{tag}: R no quoted code")
        for column, entry_list in (("quote", entries), ("assertion", ENTRY.findall(asserts))):
            for letter, number, code in entry_list:
                real = src_line(letter, int(number))
                if real is None:
                    fails.append(f"{tag}: A {letter}:{number} beyond its file")
                elif code != real:
                    fails.append(f"{tag}: Q {letter}:{number} is not the source line: {real[:70]}")
                elif column == "assertion" and not re.search(r"assert|self\.fail", code):
                    fails.append(f"{tag}: H {letter}:{number} is not an assertion: {code[:60]}")
                quotes.append(code)
        if decision not in DECISIONS:
            fails.append(f"{tag}: R decision {decision!r}")
        for label, field in (("class", cls), ("description", does), ("decision", decision)):
            for m in BAN_RE.finditer(field):
                fails.append(f"{tag}: G overclaim word {m.group(0)!r} in {label}")
        for m in re.finditer(r"(?<![\w.:])([A-Z]):(\d+)", does):
            if src_line(m.group(1), int(m.group(2))) is None:
                fails.append(f"{tag}: A {m.group(1)}:{m.group(2)} beyond its file")
        for m in re.finditer(r"`([^`]+)`", does):
            frag = m.group(1)
            if DOTTED.fullmatch(frag):
                ok = all(re.search(r"(?<![A-Za-z_0-9])" + re.escape(w) + r"(?![A-Za-z_0-9])", pool_text)
                         for w in frag.split("."))
            else:
                ok = frag.isascii() and any(_norm(frag) in n for n in normed.values())
            if not ok:
                fails.append(f"{tag}: B fragment not verbatim in the sources: `{frag}`")
        plain = re.sub(r"`[^`]*`", " ", does)
        plain = re.sub(r"(?<![\w.]):\d+(?:-:\d+)?|\b[A-Z]:\d+", " ", plain)
        have = {float(x) for x in re.findall(r"(?<![\w])(\d+(?:\.\d+)?|\.\d+)(?![\w])", "\n".join(quotes))}
        for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?|\.\d+)(?![\w])", plain):
            if float(m.group(1)) not in have:
                fails.append(f"{tag}: D number {m.group(1)} occurs in none of the row's quoted lines")
    if grep_text is not None:
        named = re.search(r"name-only lines: ([0-9, ]+)", text)
        name_only = {int(x) for x in re.findall(r"\d+", named.group(1))} if named else set()
        grep_lines = [int(line.split(":", 1)[0]) for line in grep_text.splitlines() if line.strip()]
        missing = [n for n in grep_lines if n not in covered and n not in name_only]
        if missing:
            fails.append(f"C grep lines inside no Covers range: {missing}")
    return len(rows), fails


def problems(text, repo, files):
    """The package check: text = the brief; repo = the policy checkout; files = {name: bytes} of the package.

    No table -> []. Sources are read from the repo; the optional grep log is the package file named
    '*timing-tokens*.log' (coverage rule C).
    """
    import pathlib
    found = find_table(text)
    if found is None:
        return []
    names = source_map(found[0][2]) if len(found[0]) == 6 else {}
    if not names:
        return ["table header names no sources: write '(verbatim, T = <path>, P = <path>)' in the third column"]
    sources, out = {}, []
    for letter, rel in names.items():
        path = pathlib.Path(repo) / rel
        if not path.is_file():
            out.append(f"source {letter} = {rel} not found in the policy repo")
        else:
            sources[letter] = path.read_text(encoding="utf-8").split("\n")
    if out:
        return out
    grep = next((files[n].decode("utf-8", "replace") for n in sorted(files) if re.search(r"timing-tokens.*\.log$", n)), None)
    return check(text, sources, grep)[1]
