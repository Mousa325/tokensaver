"""Package checks: sha and size listings, and the result rows a brief must hold.

A result row is | <rule> | <file> | <result> |. Rules are listed by the policy (result_rules).
Fix rounds (a package that answers a reviewer's findings) also carry the root-cause tables: every
finding with its class, the sites checked and the root cause fixed, and for every open finding one
'similar' and one 'dependents' search whose hit count is recomputed over base.zip and the package.
"""

import hashlib
import io
import re
import zipfile

SUMS = re.compile(r"([0-9a-f]{64}) [ *](.+)")
SIZES = re.compile(r"(\d+)\s+(.+)")


def _listing(text, pattern):
    entries = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = pattern.fullmatch(line.rstrip("\r"))
        if not match:
            return None
        entries[match.group(2)] = match.group(1)
    return entries


def sums_sizes_problems(files, sums_text, sizes_text):
    """files: {name: bytes} for the package, without the two listings. Return a list of problems."""
    hashes = _listing(sums_text, SUMS)
    lengths = _listing(sizes_text, SIZES)
    if hashes is None or lengths is None:
        return ["listing grammar: regenerate SHA256SUMS.txt and SIZES.txt"]
    problems = []
    for label, listing in (("SHA256SUMS", hashes), ("SIZES", lengths)):
        if set(listing) != set(files):
            problems.append(f"{label}: listed-not-present {sorted(set(listing) - set(files))} "
                            f"present-not-listed {sorted(set(files) - set(listing))}")
    for name, data in files.items():
        if name in hashes and hashes[name] != hashlib.sha256(data).hexdigest():
            problems.append(name + " sha mismatch")
        if name in lengths and int(lengths[name]) != len(data):
            problems.append(name + " size mismatch")
    return problems


def result_rows_missing(text, rules):
    """Return the <rule> rules with no result row in the markdown text (a row: | <rule> | result |)."""
    rows = []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows.append(cells)
    found = {row[0].upper() for row in rows if len(row) >= 2 and row[1]}
    return [rule for rule in rules if rule not in found]


def changed_paths(patch_text):
    """Paths named by '+++ b/' lines of a patch (same rule as core.out_of_scope)."""
    return [line[6:].strip() for line in patch_text.splitlines() if line.startswith("+++ b/")]


def result_rows_missing_per_file(text, paths, rules):
    """Each rule for each changed file. A row is | <rule> | <file> | <result> |.

    Return a list of (path, rule) pairs with no such row.
    """
    rows = []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    missing = []
    for path in paths:
        for rule in rules:
            if not any(len(row) >= 3 and row[0].upper() == rule and row[1] == path and row[2]
                       for row in rows):
                missing.append((path, rule))
    return missing


FINDING_COLUMNS = ("finding", "finding class", "sites checked", "root cause fixed")
SITE_REF = re.compile(r"[\w/.-]+\.\w+|:\d+")
SITE = re.compile(r"[\w/.-]+\.\w+(?::\d+(?:-\d+)?)?")
ONLY_SITE = re.compile(r"only site\s*:\s*\S", re.IGNORECASE)
ROOT_CAUSE = re.compile(r"cause\s*:\s*\S+(\s+\S+){2}", re.IGNORECASE)


def _table_cells(text):
    return [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.lstrip().startswith("|")]


def review_open(review_texts):
    """True when a REVIEW carried in the package asked for changes (CHANGES_REQUIRED near its top) or names roots."""
    return any("CHANGES_REQUIRED" in "\n".join(t.splitlines()[:40]) or reviewer_roots(t) for t in review_texts)


def variant_sweep_applies(text, reviews=()):
    """True for a brief whose 'Round:' field is 2 or more, or whose package carries a REVIEW that asked for
    changes: a fix of reviewed findings is a later round whatever its Round: field says (a rebase renames the task).
    """
    round_field = next((line[len("Round:"):].strip() for line in text.splitlines() if line.startswith("Round:")), "")
    later = round_field[:1].isdigit() and int(re.match(r"\d+", round_field).group(0)) >= 2
    return later or review_open(reviews)


def variant_sweep_problems(text, reviews=()):
    """(b)+(c) For a brief of round 2 or more: a variant-sweep table
    | Finding | Finding class | Sites checked | Root cause fixed | (every finding once, each with a class, every site
    of the class or 'only site: <reason>', and the file:line of the root-cause fix) and a 'Class-walk test:' line.

    Return a list of problems; an empty list for round 1 or no round field.
    """
    if not variant_sweep_applies(text, reviews):
        return []
    problems = []
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("|")
                  and [c.strip().lower() for c in line.strip().strip("|").split("|")[:4]] == list(FINDING_COLUMNS)), None)
    if start is None:
        problems.append("variant sweep: table '| Finding | Finding class | Sites checked | Root cause fixed |' missing")
    else:
        body = []
        for line in lines[start + 2:]:
            if not line.lstrip().startswith("|"):
                break
            body.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        if not body:
            problems.append("variant sweep: the table has no row")
        seen = {}
        for row in body:
            if len(row) < 3 or not row[0] or not row[1] or not SITE_REF.search(row[2]):
                problems.append(f"variant sweep: row for {row[0] or '?'} needs a class and the sites checked (file or :line)")
            elif len(set(SITE.findall(row[2]))) < 2 and not ONLY_SITE.search(row[2]):
                problems.append(f"variant sweep: row for {row[0]} names one site; list every site of the class "
                                "or write 'only site: <reason>'")
            if len(row) < 4 or not SITE_REF.search(row[3]) or not ROOT_CAUSE.search(row[3]):
                problems.append(f"variant sweep: row for {row[0] or '?'} needs the root cause fixed: 'cause: <the root "
                                "cause in words>' and the file:line of the fix at the source, not only the symptom")
            key = row[0].lower()
            if key in seen:
                problems.append(f"variant sweep: finding {row[0]} appears twice; a reopened finding is one item")
            seen[key] = True
    walk = [line for line in text.splitlines() if line.startswith("Class-walk test:")]
    if len(walk) != 1 or not SITE_REF.search(walk[0][len("Class-walk test:"):]):
        problems.append("variant sweep: exactly one 'Class-walk test: <file or test>' line is required")
    return problems


def class_walk_problems(text, paths, reviews=()):
    """For a brief of round 2 or more whose package changes files: the file named on the 'Class-walk test:' line
    must be one of the changed paths, so the class test is part of the change and not an old log.

    Return a list of problems; an empty list when the rule does not apply or the line is absent (reported elsewhere).
    """
    if not variant_sweep_applies(text, reviews) or not paths:
        return []
    walk = [line[len("Class-walk test:"):] for line in text.splitlines() if line.startswith("Class-walk test:")]
    if len(walk) != 1:
        return []
    named = {m.split(":")[0] for m in SITE.findall(walk[0])}
    if any(path == name or path.endswith("/" + name) for name in named for path in paths):
        return []
    return [f"class walk: the test named on 'Class-walk test:' ({walk[0].strip()}) is not a changed file of the package"]


FINDING_ID = re.compile(r"\b[A-Z][A-Z0-9]{0,5}-[A-Z]?\d{2}\b")


def reviewer_roots(review_text):
    """Map each finding id of a REVIEW.md to the text of its 'Root cause:' line (the id last named above it)."""
    roots, current = {}, None
    for raw in review_text.splitlines():
        line = raw.strip().lstrip("-*> ").replace("**", "")
        if line.lower().startswith("root cause:"):
            if current:
                roots[current] = line[len("root cause:"):].strip()
            continue
        found = FINDING_ID.search(line[:40])
        if found and (raw.lstrip().startswith(("#", "|")) or line.startswith(found.group(0))):
            current = found.group(0)
    return roots


def _words(text):
    return {w for w in re.findall(r"[^\W\d_]{4,}", text.lower())}


def root_match_problems(brief_text, review_texts):
    """Round 2+: every finding the reviewer gave a root cause must have a sweep row, and the row's 'cause:' text
    must name that root (share a word of four letters or more with it). Reviews without 'Root cause:' lines
    (older format) have nothing to match.
    """
    if not variant_sweep_applies(brief_text, review_texts):
        return []
    roots = {}
    for text in review_texts:
        roots.update(reviewer_roots(text))
    if not roots:
        return []
    rows = {}
    for row in _table_cells(brief_text):
        if len(row) >= 4 and FINDING_ID.fullmatch(row[0].strip()):
            rows[row[0].strip().upper()] = row[3]
    problems = []
    for finding, root in sorted(roots.items()):
        cell = rows.get(finding.upper())
        if cell is None:
            problems.append(f"root cause: finding {finding} of the review has no row in the sweep table")
        elif not (_words(cell.split("cause:", 1)[-1]) & _words(root)):
            problems.append(f"root cause: the row for {finding} does not name the reviewer's root ({root[:80]})")
    return problems


SEARCH_COLUMNS = ("finding", "kind", "search", "paths", "hits")
SEARCH_KINDS = ("similar", "dependents")
SHORT_IDS = re.compile(r"\b([A-Z][A-Z0-9]{0,5}-[A-Z]?)(\d{2})((?:/\d{2})+)")
MAX_SEARCHED_BYTES = 2_000_000


def open_findings(review_texts):
    """Finding ids a REVIEW left open: every id with a 'Root cause:' line, and every id on a NOT_CLOSED line
    (the short form R6-01/03/04 names R6-01, R6-03 and R6-04)."""
    found = set()
    for text in review_texts:
        found.update(reviewer_roots(text))
        for line in text.splitlines():
            if "NOT_CLOSED" not in line:
                continue
            found.update(FINDING_ID.findall(line))
            for prefix, first, rest in SHORT_IDS.findall(line):
                found.update(prefix + number for number in [first] + rest.strip("/").split("/"))
    return found


def _table(text, columns):
    """Rows (lists of cells) of the first pipe table whose header starts with the given column names."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("|")
                  and [c.strip().lower() for c in line.strip().strip("|").split("|")[:len(columns)]] == list(columns)),
                 None)
    if start is None:
        return None
    rows = []
    for line in lines[start + 2:]:
        if not line.lstrip().startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _base_texts(base_zip):
    """{path: text} of the text files in base.zip (binary and oversized files left out)."""
    texts = {}
    with zipfile.ZipFile(io.BytesIO(base_zip)) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.file_size > MAX_SEARCHED_BYTES:
                continue
            data = archive.read(info)
            if b"\0" not in data:
                texts[info.filename] = data.decode("utf-8", "replace")
    return texts


PACKAGE_CODE = (".py", ".ps1", ".cmd", ".bat", ".json", ".mq5", ".mqh", ".toml", ".yaml", ".yml", ".cfg", ".ini")


def _new_file_texts(patch_text):
    """{path: text} of the files a patch creates (their added lines), so a search sees code that is not in base."""
    texts, current = {}, None
    for line in patch_text.splitlines():
        if line.startswith("--- "):
            current = "" if line[4:].strip() == "/dev/null" else None
        elif line.startswith("+++ ") and current == "":
            current = line[4:].strip().removeprefix("b/")
            texts[current] = []
        elif current and line.startswith("+"):
            texts[current].append(line[1:])
        elif line.startswith("diff --git"):
            current = None
    return {path: "\n".join(lines) for path, lines in texts.items() if not path.endswith(".md")}


def package_texts(package_files):
    """{path: text} of the code a package brings besides base.zip: its own code files (refs/ generators,
    scripts) and every file its patches create. Prose (.md/.txt) is left out so a brief never matches itself."""
    texts = {}
    for name, data in (package_files or {}).items():
        path = str(name).replace("\\", "/")
        if path.endswith((".diff", ".patch")):
            texts.update(_new_file_texts(data.decode("utf-8", "replace")))
        elif path.endswith(PACKAGE_CODE) and b"\0" not in data and len(data) <= MAX_SEARCHED_BYTES:
            texts.setdefault(path, data.decode("utf-8", "replace"))
    return texts


def _covered(path, cell):
    sites = {m.split(":")[0] for m in SITE.findall(cell)}
    return path in cell or any(path == s or path.endswith("/" + s) for s in sites)


def class_search_problems(brief_text, review_texts, base_zip, package_files=None):
    """A fix of reviewed findings proves its sweep covered the whole class, not the reviewer's examples:
    a table | Finding | Kind | Search | Paths | Hits | where every swept finding and every finding the review
    left open (NOT_CLOSED or with a root cause) has a 'similar' row (a search for every other site of the same
    defect) and a 'dependents' row (a search for every caller or consumer of the root). The checker runs each
    `regex` over the base tree, the package's own code files and the files its patches create, under the named
    path prefixes; the hit count must equal Hits, the search must find
    something, and every file it hits must be named in that finding's 'Sites checked' cell (fixed, or
    'excluded: <file> <reason>').

    Return a list of problems; an empty list when no sweep applies.
    """
    if not variant_sweep_applies(brief_text, review_texts):
        return []
    sweep = {row[0].upper(): row[2] if len(row) > 2 else "" for row in _table(brief_text, FINDING_COLUMNS) or []
             if row and row[0]}
    required = set(sweep) | {f.upper() for f in open_findings(review_texts)}
    rows = _table(brief_text, SEARCH_COLUMNS)
    if rows is None:
        return [("class search: table '| Finding | Kind | Search | Paths | Hits |' missing; give the searches that "
                 "find every similar site and every dependent of each root, with their hit counts")]
    problems = []
    for row in rows:
        if len(row) < 2 or row[1].lower() not in SEARCH_KINDS:
            problems.append(f"class search: row for {row[0] if row else '?'} needs Kind 'similar' or 'dependents'")
    for finding in sorted(required):
        for kind in SEARCH_KINDS:
            if not any(len(row) > 1 and row[0].upper() == finding and row[1].lower() == kind for row in rows):
                problems.append(f"class search: finding {finding} has no '{kind}' search row")
    if base_zip is None:
        return problems + ["class search: base.zip is needed in the package to run the searches"]
    texts = _base_texts(base_zip)
    for path, text in package_texts(package_files).items():
        texts.setdefault(path, text)
    for row in rows:
        finding = row[0].upper() if row else "?"
        pattern = re.search(r"`([^`]+)`", row[2]) if len(row) > 2 else None
        hits = re.fullmatch(r"\s*(\d+)\s*", row[4]) if len(row) > 4 else None
        if pattern is None or hits is None:
            problems.append(f"class search: row for {finding} needs a `regex` in Search and a number in Hits")
            continue
        try:
            regex = re.compile(pattern.group(1))
        except re.error as error:
            problems.append(f"class search: row for {finding}: the regex does not compile ({error})")
            continue
        prefixes = [p.strip().strip("`").replace("\\", "/") for p in row[3].split(",") if p.strip().strip("`")]
        count, files = 0, set()
        for path, text in texts.items():
            if prefixes and not any(path.startswith(p) for p in prefixes):
                continue
            matched = sum(1 for line in text.splitlines() if regex.search(line))
            if matched:
                count += matched
                files.add(path)
        if count == 0:
            problems.append(f"class search: row for {finding} finds nothing in the base tree or the package; the search does not "
                            "describe the class")
        elif count != int(hits.group(1)):
            problems.append(f"class search: row for {finding} says {hits.group(1)} hits, base + package have {count}")
        cell = sweep.get(finding, "")
        missed = sorted(path for path in files if not _covered(path, cell))
        if missed:
            problems.append(f"class search: finding {finding}: hit file(s) not in its Sites checked: "
                            + ", ".join(missed[:8]) + (" ..." if len(missed) > 8 else ""))
    return problems
