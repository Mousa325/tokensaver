"""Routing artifacts: outbox copy and sha256 stamp on PASS, returned note on RETURN, audit line on both."""

import datetime
import hashlib
import pathlib
import tempfile
import unittest

from tools.checker2 import route

NOW = datetime.datetime(2026, 10, 29, 8, 0, 0, tzinfo=datetime.timezone.utc)
STAMP = "20261029T080000Z"
GOOD = "From: planner\nTo: owner\nSent: 2026-10-26T12:00:00Z\nBasic idea: x\nTask scope: x\n"


class RouteTest(unittest.TestCase):
    def test_pass_writes_outbox_copy_stamp_and_audit(self):
        with tempfile.TemporaryDirectory() as root:
            rootp = pathlib.Path(root)
            req = rootp / "req.md"
            req.write_bytes(GOOD.encode("utf-8"))
            self.assertEqual(route.send(req, rootp, rootp, NOW), "PASS")
            target = rootp / "exchange" / "outbox" / "owner" / f"{STAMP}-req.md"
            self.assertEqual(target.read_bytes(), GOOD.encode("utf-8"))
            digest = hashlib.sha256(req.read_bytes()).hexdigest()
            stamp_file = target.with_name(target.name + ".PASS.txt")
            self.assertEqual(stamp_file.read_text(encoding="utf-8"), f"PASS {STAMP} sha256={digest}\n")
            audit = (rootp / "exchange" / "audit.log").read_text(encoding="utf-8")
            self.assertEqual(audit, f"{STAMP} | planner -> owner | req.md | PASS | \n")

    def test_return_writes_note_and_audit_without_outbox(self):
        with tempfile.TemporaryDirectory() as root:
            rootp = pathlib.Path(root)
            req = rootp / "req.md"
            req.write_bytes(b"From: reviewer\nTo: coder\n")
            self.assertEqual(route.send(req, rootp, rootp, NOW), "RETURN")
            note = rootp / "exchange" / "returned" / "reviewer" / f"{STAMP}-req.md.RETURN.txt"
            self.assertTrue(note.read_text(encoding="utf-8").startswith("RETURNED to reviewer\n- missing field: Sent"))
            self.assertFalse((rootp / "exchange" / "outbox").exists())
            audit = (rootp / "exchange" / "audit.log").read_text(encoding="utf-8")
            self.assertIn(f"{STAMP} | reviewer -> coder | req.md | RETURN | ", audit)


if __name__ == "__main__":
    unittest.main()
