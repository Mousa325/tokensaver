"""The report: the only output of the checker.

verdict PASS or RETURNED; reasons carry rule, item and fix; unverified lists what a machine cannot judge.
A PASS is mechanical only: it never means the code runs on the target machine (unverified always prints).
"""

import json


def build_report(results, unverified):
    """results: list of {item, status, detail, reasons: [{rule, item, fix}]}."""
    reasons = [reason for result in results for reason in result.get("reasons", [])]
    return {
        "schema_version": 1,
        "verdict": "RETURNED" if reasons else "PASS",
        "checks": [{"item": r["item"], "status": r["status"], "detail": r.get("detail", "")} for r in results],
        "reasons": [{"rule": r["rule"], "item": r["item"], "fix": r["fix"]} for r in reasons],
        "unverified": sorted(unverified),
    }


def dumps_report(report):
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)


def exit_code(report):
    return 0 if report["verdict"] == "PASS" else 2
