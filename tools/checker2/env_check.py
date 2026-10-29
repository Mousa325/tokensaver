"""Environment checks: absolute python that exists, enough free disk, short TEMP, autocrlf off."""

import os
import pathlib
import shutil

MAX_TEMP_LEN = 240


def env_problems(python, min_free_bytes, temp, autocrlf):
    problems = []
    if not pathlib.Path(python).is_absolute() or not pathlib.Path(python).exists():
        problems.append(f"python is not an existing absolute path: {python}")
    free = shutil.disk_usage(os.getcwd()).free
    if free < min_free_bytes:
        problems.append(f"free disk {free} bytes is below {min_free_bytes}")
    if len(temp) >= MAX_TEMP_LEN:
        problems.append(f"TEMP is {len(temp)} characters, must be under {MAX_TEMP_LEN}")
    if str(autocrlf).lower() != "false":
        problems.append(f"core.autocrlf is {autocrlf!r}, must be false")
    return problems
