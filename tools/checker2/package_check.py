"""Package checks: sha and size listings, and the result rows a brief must hold.

A result row is | <rule> | <file> | <result> |. Rules are listed by the policy (result_rules).
"""

import hashlib
import re

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
