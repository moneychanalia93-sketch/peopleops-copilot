import sqlite3
import unittest

from peopleops import audit
from tests.helpers import make_conn


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        audit.log(self.conn, "E006", "test.one", {"n": 1})
        audit.log(self.conn, "E006", "test.two", {"email": "a.b@corp.example"})

    def test_update_and_delete_are_blocked(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE audit_log SET actor='x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM audit_log")

    def test_chain_verifies(self):
        self.assertTrue(audit.verify_chain(self.conn)["ok"])

    def test_pii_is_redacted_before_storage(self):
        self.assertNotIn("a.b@corp", self.conn.execute("SELECT detail FROM audit_log WHERE action='test.two'").fetchone()[0])

    def test_tampering_is_detected_even_if_triggers_are_dropped(self):
        self.conn.execute("DROP TRIGGER audit_no_update")
        self.conn.execute("UPDATE audit_log SET detail='{}' WHERE action='test.one'")
        result = audit.verify_chain(self.conn)
        self.assertFalse(result["ok"])
        self.assertIn("broken_at", result)


if __name__ == "__main__":
    unittest.main()
