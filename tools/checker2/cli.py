"""One entry point: python -m tools.checker2 --config <policy.json> --package <dir> [--brief <file>].

Reads the project policy (plain JSON), runs the live-state, environment, package and command
checks, prints the report as JSON. Exit 0 PASS, 2 RETURNED. The checker writes nothing.
"""

import argparse
import json
import os
import pathlib
import sys

from tools.checker2 import core, env_check, package_check, report, request

SEAL_FILES = ("SHA256SUMS.txt", "SIZES.txt")


def run(config, package_dir, brief_text, temp, request_text=None):
    """config: policy dict. Returns the report dict."""
    results = []

    live_all = core.live_state(config["repo"], config["expected_branch"], config["lock_file"])
    unverified = [p for p in live_all if p.startswith("UNVERIFIED")]
    live = [p for p in live_all if not p.startswith("UNVERIFIED")]
    status = "FAIL" if live else ("UNVERIFIED" if unverified else "PASS")
    results.append({"item": "live", "status": status, "detail": "; ".join(live_all),
                    "reasons": [{"rule": "live", "item": "live", "fix": p} for p in live]})

    env = env_check.env_problems(config["python"], config["min_free_bytes"], temp,
                                 os.environ.get("CHECKER_AUTOCRLF", "false"))
    results.append({"item": "env", "status": "FAIL" if env else "PASS", "detail": "; ".join(env),
                    "reasons": [{"rule": "env", "item": "env", "fix": p} for p in env]})

    root = pathlib.Path(package_dir)
    files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
             if p.is_file() and p.name not in SEAL_FILES}
    sums = (root / "SHA256SUMS.txt").read_text(encoding="utf-8") if (root / "SHA256SUMS.txt").is_file() else ""
    sizes = (root / "SIZES.txt").read_text(encoding="utf-8") if (root / "SIZES.txt").is_file() else ""
    pkg = package_check.sums_sizes_problems(files, sums, sizes)
    results.append({"item": "package", "status": "FAIL" if pkg else "PASS", "detail": "; ".join(pkg),
                    "reasons": [{"rule": "package", "item": "package", "fix": p} for p in pkg]})

    rules = config.get("result_rules", [])
    if brief_text is not None and rules:
        missing = package_check.result_rows_missing(brief_text, rules)
        results.append({"item": "result-rows", "status": "FAIL" if missing else "PASS",
                        "detail": ", ".join(missing),
                        "reasons": [{"rule": "result", "item": "result-rows", "fix": f"add result rows for {m}"}
                                    for m in missing]})
        patches = [files[name] for name in files if name.endswith((".diff", ".patch"))]
        paths = sorted({p for raw in patches for p in package_check.changed_paths(raw.decode("utf-8", "replace"))})
        per_file = package_check.result_rows_missing_per_file(brief_text, paths, rules)
        results.append({"item": "result-per-file", "status": "FAIL" if per_file else "PASS",
                        "detail": f"{len(paths)} changed file(s)",
                        "reasons": [{"rule": "result", "item": path, "fix": f"add a | {rule} | {path} | result | row"}
                                    for path, rule in per_file]})

    for index, gate in enumerate(config.get("command_checks", [])):
        ok = core.gate_passes(gate["check"], gate["expect"], config["repo"])
        results.append({"item": f"command-{index}", "status": "PASS" if ok else "FAIL",
                        "detail": gate["check"],
                        "reasons": [] if ok else [{"rule": "command", "item": gate["check"],
                                                   "fix": "reader output does not match EXPECT"}]})

    log_path = config.get("runner_log")
    if log_path and config.get("task_id"):
        log_text = pathlib.Path(log_path).read_text(encoding="utf-8", errors="replace") if pathlib.Path(log_path).is_file() else ""
        gone = core.job_abandoned(log_text, config["task_id"])
        job_lock = pathlib.Path(config.get("job_lock", config["lock_file"]))
        running = job_lock.exists() and core.lock_holder_state(job_lock) == "live"
        abandoned = gone and not running
        status = "FAIL" if abandoned else ("RUNNING" if gone else "PASS")
        results.append({"item": "abandon", "status": status, "detail": config["task_id"],
                        "reasons": [{"rule": "abandon", "item": config["task_id"],
                                     "fix": "job stopped unfinished: hand off, do not count as passed"}] if abandoned else []})

    if request_text is not None:
        reasons = request.check(request_text, pathlib.Path(config.get("request_root", config["repo"])), config["repo"])
        results.append({"item": "request", "status": "FAIL" if reasons else "PASS", "detail": "; ".join(reasons),
                        "reasons": [{"rule": "request", "item": "request", "fix": r} for r in reasons]})

    if config.get("operator_field") and brief_text is not None:
        field = config["operator_field"]
        named = [line for line in brief_text.splitlines() if line.startswith(field) and line[len(field):].strip()]
        results.append({"item": "operator", "status": "PASS" if named else "FAIL", "detail": field,
                        "reasons": [] if named else [{"rule": "operator", "item": field,
                                                      "fix": f"add a '{field}' line with a name"}]})

    if config.get("allowed_paths") is not None:
        bad = []
        for name, raw in files.items():
            if name.endswith((".diff", ".patch")):
                outside = core.out_of_scope(raw.decode("utf-8", "replace"), config["allowed_paths"])
                if outside:
                    bad.append(outside)
        results.append({"item": "scope", "status": "FAIL" if bad else "PASS", "detail": ", ".join(bad),
                        "reasons": [{"rule": "scope", "item": b, "fix": "path outside Allowed paths"} for b in bad]})

    if brief_text is not None:
        cited = [line[len("- cited:"):].strip() for line in brief_text.splitlines() if line.startswith("- cited:")]
        absent = [c for c in cited if c not in files]
        results.append({"item": "cited", "status": "FAIL" if absent else "PASS", "detail": ", ".join(absent),
                        "reasons": [{"rule": "cited", "item": c, "fix": "cited file is not in the package"}
                                    for c in absent]})

    banned = [c for c in config.get("banned_commands", []) if brief_text and c in brief_text]
    results.append({"item": "banned", "status": "FAIL" if banned else "PASS", "detail": ", ".join(banned),
                    "reasons": [{"rule": "banned", "item": c, "fix": "remove banned command"} for c in banned]})

    return report.build_report(results, config.get("needs_human", []) + unverified)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Checker.")
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--package", type=pathlib.Path, required=True)
    parser.add_argument("--brief", type=pathlib.Path, default=None)
    parser.add_argument("--request", type=pathlib.Path, default=None, help="request file to check (header rules)")
    parser.add_argument("--temp", default=os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")))
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    brief = args.brief.read_text(encoding="utf-8") if args.brief else None
    request_text = args.request.read_text(encoding="utf-8") if args.request else None
    result = run(config, args.package, brief, args.temp, request_text)
    print(report.dumps_report(result))
    return report.exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
