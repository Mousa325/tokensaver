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

1. Run the unit tests from the root folder. All 32 should pass. Name the test modules as shown:
   `python -m unittest discover` finds none in this layout.

       python -m unittest tests.test_checker2 tests.test_checker2_request tests.test_checker2_route

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
- A coder report must contain the section `Choices not covered`.

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
  `request_gate.py` (check only, writes nothing), `package_check.py`, `core.py`, `env_check.py`,
  `report.py`, `cli.py`.
- `tests/`: unit tests for each part.
- `policy-example.json`, `request-template.md`, `run-check.cmd`, `WALKTHROUGH.md`.

## License

MIT. See `LICENSE`.
