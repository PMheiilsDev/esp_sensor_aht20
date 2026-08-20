import os
import sqlite3
import json
import unittest
from datetime import datetime, timedelta

# Mock configuration before importing modules that depend on it
# To avoid polluting the real database, we will use a test database file
import sys
import shutil

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# We can override conf settings for testing
import conf
conf.DB_FILE = "test_sensor_data.db"
conf.OLD_DATA_FILE = "test_data.txt"

# Now import the modules under test
import db


class TestSQLiteStorage(unittest.TestCase):

    def setUp(self):
        # Ensure clean state before each test
        self.cleanup_files()

    def tearDown(self):
        # Clean up after each test
        self.cleanup_files()

    def cleanup_files(self):
        for f in ["test_sensor_data.db", "test_data.txt", "test_data.txt.bak"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
            # Also clean up WAL files if any
            for suffix in ["-wal", "-shm"]:
                if os.path.exists(f + suffix):
                    try:
                        os.remove(f + suffix)
                    except Exception:
                        pass

    def test_database_initialization_and_migration(self):
        # 1. Create a dummy test_data.txt file
        dummy_records = [
            {"time": "2026-08-15T12:00:00.000000", "temperature": 25.5, "humidity": 60.0, "vbat": 4.12, "power_save": False},
            {"time": "2026-08-15T13:00:00.000000", "temperature": 26.0, "humidity": 58.5, "vbat": 4.10, "power_save": True},
            {"time": "2026-08-15T14:00:00.000000", "temperature": 24.8, "humidity": 62.1, "vbat": 4.09, "power_save": False},
        ]
        
        # Override old data file in db module to point to our test file
        db.OLD_DATA_FILE = "test_data.txt"
        db.DB_FILE = "test_sensor_data.db"

        with open("test_data.txt", "w", encoding="utf-8") as f:
            for r in dummy_records:
                f.write(json.dumps(r) + "\n")

        # 2. Run initialization (which should trigger migration)
        db.init_db()

        # 3. Assert old file is renamed to test_data.txt.bak
        self.assertFalse(os.path.exists("test_data.txt"))
        self.assertTrue(os.path.exists("test_data.txt.bak"))

        # 4. Assert data is in SQLite db
        conn = db.get_db()
        rows = conn.execute("SELECT * FROM sensor_data ORDER BY time ASC").fetchall()
        self.assertEqual(len(rows), 3)

        # Check values
        self.assertEqual(rows[0]["time"], "2026-08-15T12:00:00.000000")
        self.assertEqual(rows[0]["temperature"], 25.5)
        self.assertEqual(rows[0]["humidity"], 60.0)
        self.assertEqual(rows[0]["vbat"], 4.12)
        self.assertEqual(rows[0]["power_save"], 0)

        self.assertEqual(rows[1]["time"], "2026-08-15T13:00:00.000000")
        self.assertEqual(rows[1]["power_save"], 1)

        # 5. Test min/max query
        row_range = conn.execute("SELECT MIN(time) as min_t, MAX(time) as max_t FROM sensor_data").fetchone()
        self.assertEqual(row_range["min_t"], "2026-08-15T12:00:00.000000")
        self.assertEqual(row_range["max_t"], "2026-08-15T14:00:00.000000")

        # 6. Test filtering query
        rows_filtered = conn.execute(
            "SELECT * FROM sensor_data WHERE time >= ? AND time <= ?",
            ("2026-08-15T12:30:00", "2026-08-15T13:30:00")
        ).fetchall()
        self.assertEqual(len(rows_filtered), 1)
        self.assertEqual(rows_filtered[0]["time"], "2026-08-15T13:00:00.000000")

        conn.close()


if __name__ == "__main__":
    unittest.main()
