@echo off
rem Runs the request check and routes the request (stamp on PASS, returned note on RETURN).
rem Usage: run-check.cmd <request.md>
rem Needs Python on PATH. Exit 0 = PASS, 1 = RETURN. Output: PASS or RETURN with reasons.
set "PYTHONPATH=%~dp0"
python "%~dp0tools\checker2\route.py" %*
