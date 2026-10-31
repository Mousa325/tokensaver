"""Optional report-only steps: Hypothesis property tests, Cosmic Ray mutation run, Semgrep pattern scan.

Opt-in (cli --extras). Never blocking: a step reports status INFO or SKIPPED and adds no reason, so the
verdict is unchanged. Nothing runs in the repo: the targets and their tests are copied to a temp
directory and the tool runs there. Tools come from one pip venv named in the policy (extras.venv);
the checker never installs anything (setup is the separate command `python -m tools.checker2.extras
--setup <venv>`). The detail in the report holds counts only; full tool output goes to --extras-out.

Policy block (all keys optional except venv):
  "extras": {"venv": "<dir>", "timeout_s": 600,
             "hypothesis": {"tests": ["tests/props/test_x.py"]},
             "cosmic_ray": {"module": "src/x/y.py", "tests": ["tests/test_y.py"]},
             "semgrep": {"rules": "tools/semgrep-rules.yml", "paths": ["src/x"]}}
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

PINNED = ("pytest", "hypothesis", "cosmic-ray", "semgrep")


def venv_bin(venv, name):
    base = pathlib.Path(venv) / ("Scripts" if os.name == "nt" else "bin")
    for cand in (base / (name + ".exe"), base / name):
        if cand.is_file():
            return str(cand)
    return None


def copy_into(repo, rels, dest):
    """Copy repo-relative files into dest keeping their paths; returns the missing ones."""
    missing = []
    for rel in rels:
        src = pathlib.Path(repo) / rel
        if src.is_dir():
            shutil.copytree(src, pathlib.Path(dest) / rel, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", ".git"))
        elif src.is_file():
            (pathlib.Path(dest) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, pathlib.Path(dest) / rel)
        else:
            missing.append(rel)
    return missing


def run_tool(argv, cwd, timeout_s, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, env=env, check=False)
        return done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, f"timeout after {timeout_s}s\n{(exc.stdout or b'')!r}"
    except OSError as exc:
        return 127, str(exc)


def step(item, status, detail, output=""):
    return {"item": item, "status": status, "detail": detail, "reasons": [], "output": output}


def hypothesis_step(cfg, repo, venv, work, timeout_s):
    py = venv_bin(venv, "python")
    if not py:
        return step("extras-hypothesis", "SKIPPED", "venv has no python")
    tests = cfg.get("tests", [])
    if not tests:
        return step("extras-hypothesis", "SKIPPED", "no property tests named")
    missing = copy_into(repo, tests + cfg.get("support", []), work)
    if missing:
        return step("extras-hypothesis", "SKIPPED", "missing: " + ", ".join(missing))
    code, out = run_tool([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--hypothesis-seed=0",
                          "--hypothesis-show-statistics", *tests], work, timeout_s,
                         {"PYTHONPATH": str(work), "PYTHONDONTWRITEBYTECODE": "1"})
    if code == 127 or "No module named pytest" in out or "No module named hypothesis" in out:
        return step("extras-hypothesis", "SKIPPED", "pytest or hypothesis not installed in the venv", out)
    passed = re.search(r"(\d+) passed", out)
    failed = re.search(r"(\d+) failed", out)
    return step("extras-hypothesis", "INFO",
                f"exit {code}; passed {passed.group(1) if passed else 0}; failed {failed.group(1) if failed else 0}", out)


def cosmic_step(cfg, repo, venv, work, timeout_s):
    cr = venv_bin(venv, "cosmic-ray")
    py = venv_bin(venv, "python")
    if not cr or not py:
        return step("extras-cosmic-ray", "SKIPPED", "cosmic-ray not installed in the venv")
    module, tests = cfg.get("module"), cfg.get("tests", [])
    if not module or not tests:
        return step("extras-cosmic-ray", "SKIPPED", "module or tests not named")
    missing = copy_into(repo, [module] + tests + cfg.get("support", []), work)
    if missing:
        return step("extras-cosmic-ray", "SKIPPED", "missing: " + ", ".join(missing))
    command = " ".join([json.dumps(py), "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests])
    conf = pathlib.Path(work) / "cr.toml"
    conf.write_text(
        f'[cosmic-ray]\nmodule-path = "{module.replace(chr(92), "/")}"\ntimeout = {cfg.get("mutant_timeout_s", 30.0)}\n'
        f'excluded-modules = []\ntest-command = {json.dumps(command)}\n\n'
        '[cosmic-ray.distributor]\nname = "local"\n', encoding="utf-8")
    env = {"PYTHONPATH": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
    log = []
    session = "cr.sqlite"
    partial = False
    for args in (["init", "cr.toml", session], ["baseline", "cr.toml"], ["exec", "cr.toml", session]):
        code, out = run_tool([cr, *args], work, timeout_s, env)
        log.append(f"$ cosmic-ray {' '.join(args)} -> {code}\n{out}")
        if code != 0 and not (args[0] == "exec" and code == 124):
            return step("extras-cosmic-ray", "INFO", f"stopped at '{args[0]}' (exit {code})", "\n".join(log))
        partial = partial or code == 124
    rate_bin = venv_bin(venv, "cr-rate")
    report_bin = venv_bin(venv, "cr-report")
    rate = run_tool([rate_bin, session], work, timeout_s, env)[1].strip() if rate_bin else "n/a"
    rep = run_tool([report_bin, session], work, timeout_s, env)[1] if report_bin else ""
    log.append("$ cr-report\n" + rep)
    total = re.search(r"total jobs: (\d+)", rep)
    surv = re.search(r"surviving mutants: (\d+)", rep)
    return step("extras-cosmic-ray", "INFO",
                f"{'PARTIAL (exec timeout); ' if partial else ''}mutants {total.group(1) if total else '?'}; "
                f"surviving {surv.group(1) if surv else '?'}; survival rate {rate}", "\n".join(log))


def semgrep_step(cfg, repo, venv, work, timeout_s):
    sg = venv_bin(venv, "semgrep")
    if not sg:
        return step("extras-semgrep", "SKIPPED", "semgrep not installed in the venv (no native Windows build)")
    rules, paths = cfg.get("rules"), cfg.get("paths", [])
    if not rules or not paths:
        return step("extras-semgrep", "SKIPPED", "rules or paths not named")
    missing = copy_into(repo, [rules] + paths, work)
    if missing:
        return step("extras-semgrep", "SKIPPED", "missing: " + ", ".join(missing))
    code, out = run_tool([sg, "scan", "--config", rules, "--metrics=off", "--disable-version-check", "--json",
                          "--quiet", *paths], work, timeout_s)
    try:
        data = json.loads(out[out.index("{"):])
        n = len(data.get("results", []))
        errs = len(data.get("errors", []))
        return step("extras-semgrep", "INFO", f"findings {n}; errors {errs}", out)
    except ValueError:
        return step("extras-semgrep", "INFO", f"exit {code}; no JSON output", out)


def run_extras(config, repo, temp, out_dir=None):
    """Returns report items (status INFO or SKIPPED, never a reason). Runs only on copies in a temp dir."""
    cfg = config.get("extras")
    if not cfg or not cfg.get("venv"):
        return [step("extras", "SKIPPED", "policy has no extras.venv")]
    timeout_s = cfg.get("timeout_s", 600)
    items = []
    for name, fn in (("hypothesis", hypothesis_step), ("cosmic_ray", cosmic_step), ("semgrep", semgrep_step)):
        if name not in cfg:
            continue
        with tempfile.TemporaryDirectory(prefix="checker2-extras-", dir=temp) as work:
            items.append(fn(cfg[name], repo, cfg["venv"], work, timeout_s))
    if out_dir:
        out = pathlib.Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for it in items:
            (out / (it["item"] + ".txt")).write_text(it["status"] + " " + it["detail"] + "\n\n" + it.get("output", ""),
                                                      encoding="utf-8")
    return items or [step("extras", "SKIPPED", "no tool configured")]


def setup(venv):
    """Create the venv and install the pinned tools into it (the only place anything is installed)."""
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv_bin(venv, "python")
    subprocess.run([py, "-m", "pip", "install", "-q", *PINNED], check=False)
    return {name: bool(venv_bin(venv, name)) for name in ("pytest", "cosmic-ray", "cr-report", "semgrep")}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--setup":
        print(json.dumps(setup(sys.argv[2]), sort_keys=True))
    else:
        print("usage: python -m tools.checker2.extras --setup <venv dir>")
        sys.exit(2)
