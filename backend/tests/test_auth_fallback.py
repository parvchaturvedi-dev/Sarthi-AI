"""Local SQLite auth path — used for dev/no-env, and by the desktop backend."""

import os
import tempfile
import unittest
from pathlib import Path

from nova.auth import db


class AuthLocalStoreTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.gettempdir()) / "sarthi_auth_test.sqlite3"
        if self.db_path.exists():
            self.db_path.unlink()
        os.environ["AUTH_LOCAL_DB"] = str(self.db_path)
        os.environ.pop("MONGODB_URI", None)      # force local mode
        db.local_store._init_db(force=True)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_register_then_get_returns_the_saved_user(self):
        uid = db.register_user("user@example.com", "User", "hash")
        self.assertGreater(uid, 0)

        user = db.get_user("user@example.com")
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "user@example.com")
        self.assertEqual(user["provider"], "local")

    def test_register_duplicate_email_raises_valueerror(self):
        db.register_user("dup@example.com", "First", "h1")
        with self.assertRaises(ValueError):
            db.register_user("dup@example.com", "Second", "h2")

    def test_upsert_google_creates_then_updates_by_email(self):
        uid1 = db.upsert_google("g@example.com", "Old Name")
        uid2 = db.upsert_google("g@example.com", "New Name")
        self.assertEqual(uid1, uid2)                     # same user
        u = db.get_user("g@example.com")
        self.assertEqual(u["name"], "New Name")
        self.assertEqual(u["provider"], "google")


if __name__ == "__main__":
    unittest.main()
