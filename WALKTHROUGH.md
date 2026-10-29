# WALKTHROUGH: fresh-user run on Linux

Follows only README.md, in an empty folder that holds a copy of the public files.
Python 3.13 on Linux here (the README asks for 3.12 or newer on Windows 11; the code uses only the standard library).

```
$ python3 --version
Python 3.13.17
[exit 0]
```

```
$ python3 -m unittest tests.test_checker2 tests.test_checker2_request tests.test_checker2_route 2>&1 | tail -3
Ran 38 tests in 1.342s

OK
[exit 0]
```

```
$ cat my-request.md
From: planner
To: coder
Sent: 2026-10-29T09:08:24Z
Basic idea: Add greet function and add a test for greet so the greeting can be checked.
Task scope: Add greet function
Task scope: Add a test for greet
Pre-code study: study.md sha256=bda34fb48e660e3a723cf5b305e733d3603bcfe00c5516850c7058ad40f23059 size=59
Test list: tests-plan.md
Answers: answers.md
Plan: plan.md
Base sha: 0123456789abcdef0123456789abcdef01234567
Open choices: 0
Dependencies: none
Allowed paths: src/ tests/
Round: 1

Add greet(name) to src/greet.py and a test that checks its output.
[exit 0]
```

```
$ python3 -m tools.checker2.route my-request.md
PASS
[exit 0]
```

```
$ ls -R exchange
exchange:
audit.log
outbox

exchange/outbox:
coder

exchange/outbox/coder:
20261029T090824Z-my-request.md
20261029T090824Z-my-request.md.PASS.txt
[exit 0]
```

```
$ cat exchange/outbox/coder/*.PASS.txt
PASS 20261029T090824Z sha256=9a953f893bcbe953a69fba25c20fb2d759723f13b060a49f778efaa8f002d81f
[exit 0]
```

```
$ python3 -m tools.checker2.route broken-request.md
RETURN
[exit 1]
```

```
$ cat exchange/returned/planner/*.RETURN.txt
RETURNED to planner
- Open choices: must be 0 before coding
[exit 0]
```

```
$ cat exchange/audit.log
20261029T090824Z | planner -> coder | my-request.md | PASS | 
20261029T090824Z | planner -> coder | broken-request.md | RETURN | Open choices: must be 0 before coding
[exit 0]
```
