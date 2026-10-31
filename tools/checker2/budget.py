"""Loop and budget guard for route.py.

State file: exchange/state.json, {task_key: {"attempts": n, "returns": n}}.
A task key is the request's Task header when present, else the file name stem.
Refused (RETURN) when the same task was returned MAX_RETURNS times, or when it has
been checked MAX_ATTEMPTS times. The refusal says to stop and ask the owner.
"""

import json
import pathlib

MAX_RETURNS = 3
MAX_ATTEMPTS = 20


def task_key(head, name):
    task = head.get("Task", [""])[0].strip()
    return task or pathlib.Path(name).stem


def load(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, state):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def problems(state, key):
    entry = state.get(key, {})
    out = []
    if entry.get("returns", 0) >= MAX_RETURNS:
        out.append(f"loop limit: {key} returned {entry['returns']} times; stop and ask the owner")
    if entry.get("attempts", 0) >= MAX_ATTEMPTS:
        out.append(f"budget limit: {key} checked {entry['attempts']} times; stop and ask the owner")
    return out


def record(state, key, verdict):
    entry = state.setdefault(key, {"attempts": 0, "returns": 0})
    entry["attempts"] = entry.get("attempts", 0) + 1
    if verdict == "RETURN":
        entry["returns"] = entry.get("returns", 0) + 1
    return state
