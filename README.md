# tokensaver

A stateless gate that returns AI-agent work until it passes — fewer fix rounds, fewer tokens.

tokensaver checks a request file before the next agent or person receives it. A request that
passes is copied to the receiver's outbox with a stamp. A request that fails is returned to the
sender with every reason listed. The checker keeps no state between runs: each result depends only
on the request, the files it names, and (for dependencies) git history.

Pure Python standard library. No packages to install.

## Requirements

- Python 3.12 or newer (tested on 3.13 on Linux; Windows 11 is the target platform).
- git, only if your requests list `Dependencies` by commit sha.

## Quick start

Unpack this folder anywhere. The folder that holds `tools\` is the project root. Results go to
`exchange\` under that root.

1. Run the unit tests from the root folder. All 101 should pass. Name the test modules as shown:
   `python -m unittest discover` finds none in this layout.

       python -m unittest tests.test_checker2 tests.test_checker2_request tests.test_checker2_route tests.test_checker2_research_rules tests.test_checker2_extras tests.test_checker2_table_rows

   On Windows, use `py -3 -m unittest ...` if `python` is not on PATH.
2. Copy `request-template.md` to `my-request.md` and fill in every field (see below).
   Every file the request names (`study.md`, `tests-plan.md`, `answers.md`, `plan.md`, ...) must
   exist in the root folder before the check, and `Sent` must be written after them.
3. Check and route it:

       run-check.cmd my-request.md                  (Windows; needs python on PATH, or edit run-check.cmd to call `py -3`)
       python -m tools.checker2.route my-request.md (any OS, run from the root folder)

4. Read the answer: `PASS` or `RETURN` with the reasons. `WALKTHROUGH.md` shows a full run.

## Write a request

Start from `request-template.md`. Every header line is read by the checker.

- `From`, `To`, `Sent`, `Basic idea` and `Task scope` are required. `From` and `To` must differ and be one of:
  `planner`, `runner`, `coder`, `reviewer`, `owner`.
- Every `Task scope` item must appear, in lower case, inside `Basic idea`.
- `Sent` is an ISO time such as `2026-01-01T09:00:00Z`. Write it after the files it names,
  because a referenced file modified after `Sent` is refused.
- For a request to `coder`, also: `Pre-code study` (with `sha256=` and `size=` of the file),
  `Test list`, `Answers`, `Plan`, `Base sha` (40 hex characters), `Open choices: 0`,
  `Dependencies` (`none` or 40-hex shas), `Allowed paths`.
- An `Answers` table may not contain a row that says `later`, `TBD`, `todo` or `?`.
- A fix request that follows review notes needs `Fix rule:` with the exact rule text
  (`Run the failing review checks and sweep every place of the same class before delivery`).
- Round 2 or later must contain the words `same-class sweep`.
- A request to `reviewer` must have exactly one line that starts with `Package:`. Two or none is returned.
- A request to `reviewer` must have exactly one `Main sha:` line with the full 40-hex sha of the main branch it reviews.
- Every request needs a task body: at least one line after the blank line that ends the header block.
- A coder report must contain the section `Choices not covered`.

Review rounds (requests to `reviewer` with a `gate-kind:` line):

- The request carries three standard texts word for word (`SINGLE_PASS_TEXT`, `ROOT_CAUSE_TEXT`
  and `COVERAGE_TEXT` in `tools/checker2/request.py`): one pass with every finding, a
  `Defect:` / `Root cause:` / `Class:` line set for each finding, and a full inventory with
  `Class sites: <n>`, `Origin:` and a closing `coverage: COMPLETE` line.
- A review request may not ask for the full test suite on its `Run only:` line. The suite is its own
  request (`gate-kind: run`), filed only after a clean review and right before the merge. It names
  that review on a `Clean review:` line, and the review must pass with no open findings.

## Check a review before you relay it

    python -m tools.checker2.review_return REVIEW.md

- **PASS** (exit 0): well formed; relay it.
- **RETURN** (exit 1): a finding lacks its `Root cause:`, `Class:`, `Class sites:` or `Origin:`
  line, or there is no `coverage: COMPLETE` line.
- **CONFIRM** (exit 3): well formed, but it has findings. Send it back to the reviewer as a confirm
  pass (`CONFIRM_TEXT`) with the earlier findings inside the package, until the reviewer writes
  `confirm: NO_NEW_FINDINGS`. Only then do the findings go to the fixer.

Get a sha and size for a referenced file:

    sha256sum study.md          (Linux, macOS, Git Bash)
    certutil -hashfile study.md SHA256   (Windows)

## Results

- **PASS** (exit 0): the request is copied to `exchange\outbox\<receiver>\` with a `.PASS.txt`
  stamp holding the sha256 of the request.
- **RETURN** (exit 1): a `RETURN.txt` note with the reasons goes to `exchange\returned\<sender>\`.
- Both append one line to `exchange\audit.log`.

PASS means every mechanical rule passed. It does not mean the code works: run the tests yourself.

## Check a package (optional)

For a folder of files with a brief:

    python -m tools.checker2 --config policy.json --package <folder> --brief <brief.md>

Exit 0 = PASS, 2 = RETURNED. The folder must hold `SHA256SUMS.txt` and `SIZES.txt`, listing every
other file with its sha256 and byte size. The output is a JSON report.

A fix package that answers review findings (a `REVIEW*.md` with open findings in the folder, or
`Round: 2` or later in the brief) also needs:

- a `| Finding | Finding class | Sites checked | Root cause fixed |` table, one row per finding,
  with the sites as `file:line` and a `cause:` of at least three words;
- a `Class-walk test:` line when a changed file is named in the table;
- every root cause the reviewer wrote matched in the table;
- a `| Finding | Kind | Search | Paths | Hits |` table with one `similar` and one `dependents`
  row per open finding. Each regex is re-run over `base.zip` plus the package code, the count must
  equal `Hits`, zero hits is refused, and every file hit must be named in that finding's sites.

A brief with a table whose header starts `| Covers |` (six columns: Covers, Class, Quoted code, What the
quoted lines do, Assertion, Decision) is checked row by row against the source files named in the third
header cell: quoted lines must match the source exactly, cited line numbers must exist, descriptions may not
use overclaim words (always, never, must, guarantee, ...), and Decision is one of OK, KEPT, FIXED, EXCLUDED,
n.a. See `tools/checker2/table_rows.py` for the full list.

`--extras` also runs optional report-only tools (Hypothesis, Cosmic Ray, Semgrep) from a venv named in the
policy (`extras`); they never change the verdict. Set the venv up once with
`python -m tools.checker2.extras --setup <venv>`.

Items the checker cannot judge are listed as `unverified`. `UNVERIFIED` is never a pass.

## Policy

Copy `policy-example.json` to `policy.json` and change every value. Keys that start with `_`
explain the key after them. Main keys:

- `repo`, `expected_branch`: the git checkout and branch the package must be on.
- `lock_file`: a lock file that must not be held by a live process.
- `python`: an absolute path to Python.
- `min_free_bytes`: refuse to run below this free disk space.
- `runner_log`, `task_id`, `job_lock`: optional; tell a stopped job from a running one.
- `allowed_paths`, `banned_commands`: optional scope and text checks.
- `command_checks`: optional commands that must exit 0 and print the expected text.
- `result_rules`: optional labels. When set, the brief needs one `| label | file | result |` row
  per label for every changed file. Empty list = off.

## Layout

- `tools/checker2/`: `request.py` (request rules), `route.py` (routing writer),
  `request_gate.py` (check only, writes nothing), `review_return.py` (review check),
  `package_check.py`, `table_rows.py`, `extras.py`, `core.py`, `env_check.py`, `report.py`, `cli.py`.
- `tests/`: unit tests for each part.
- `policy-example.json`, `request-template.md`, `run-check.cmd`, `WALKTHROUGH.md`.

## License

MIT. See `LICENSE`.
