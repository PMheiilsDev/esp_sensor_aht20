import os
import json
import unittest
import sys
from datetime import datetime

# Setup test DB files
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conf
conf.DB_FILE = "test_sensor_data_aht.db"
conf.OLD_DATA_FILE = "test_data_aht.txt"

import db
import direct_aht
import website


class TestDirectAHTIntegration(unittest.TestCase):

    def setUp(self):
        self.cleanup_files()
        # Initialize test database
        db.init_db()
        self.app_client = website.app.test_client()

    def tearDown(self):
        self.cleanup_files()

    def cleanup_files(self):
        for f in ["test_sensor_data_aht.db", "test_data_aht.txt", "test_data_aht.txt.bak", "data.jsonl"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
            for suffix in ["-wal", "-shm"]:
                if os.path.exists(f + suffix):
                    try:
                        os.remove(f + suffix)
                    except Exception:
                        pass

    def test_db_initialization_contains_both_tables(self):
        # Verify both tables are created successfully
        with db.get_db() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row["name"] for row in cursor.fetchall()]
            self.assertIn("sensor_data", tables)
            self.assertIn("indoor_sensor_data", tables)

    def test_mock_sensor_falls_back_on_dev_pc(self):
        # We should be using MockSensor on dev PC since adafruit_ahtx0/board won't be present
        self.assertFalse(direct_aht.HAS_HARDWARE)
        temp, hum = direct_aht.sensor.temperature_humitity
        self.assertTrue(15.0 <= temp <= 30.0)
        self.assertTrue(10.0 <= hum <= 95.0)

    def test_direct_aht_db_write(self):
        # Write dummy indoor sensor data manually, or via simulated logic
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO indoor_sensor_data (time, temperature, humidity) VALUES (?, ?, ?)",
                ("2026-08-20T10:00:00.000000", 22.5, 45.0)
            )
            conn.commit()

        with db.get_db() as conn:
            row = conn.execute("SELECT * FROM indoor_sensor_data").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["time"], "2026-08-20T10:00:00.000000")
            self.assertEqual(row["temperature"], 22.5)
            self.assertEqual(row["humidity"], 45.0)

    def test_website_endpoints_with_both_datasets(self):
        # Seed both tables
        time1 = "2026-08-20T10:00:00"
        time2 = "2026-08-20T10:05:00"
        
        with db.get_db() as conn:
            # Seed outdoor (ESP)
            conn.execute(
                "INSERT INTO sensor_data (time, temperature, humidity, vbat, power_save) VALUES (?, ?, ?, ?, ?)",
                (time1, 18.5, 75.0, 3.95, 0)
            )
            # Seed indoor (Direct AHT)
            conn.execute(
                "INSERT INTO indoor_sensor_data (time, temperature, humidity) VALUES (?, ?, ?)",
                (time2, 22.1, 44.5)
            )
            conn.commit()

        # Test index page rendering
        response = self.app_client.get("/")
        self.assertEqual(response.status_code, 200)
        html_content = response.data.decode("utf-8")
        self.assertIn("2026-08-20T10:00", html_content) # Min date should be from outdoor
        self.assertIn("2026-08-20T10:05", html_content) # Max date should be from indoor

        # Test API endpoint
        api_response = self.app_client.get(f"/api/data?start={time1}&end={time2}")
        self.assertEqual(api_response.status_code, 200)
        data = json.loads(api_response.data.decode("utf-8"))
        
        # Verify API returned both lists
        self.assertIn("outdoor", data)
        self.assertIn("indoor", data)
        
        self.assertEqual(len(data["outdoor"]), 1)
        self.assertEqual(data["outdoor"][0]["time"], time1)
        self.assertEqual(data["outdoor"][0]["temperature"], 18.5)
        self.assertEqual(data["outdoor"][0]["vbat"], 3.95)
        
        self.assertEqual(len(data["indoor"]), 1)
        self.assertEqual(data["indoor"][0]["time"], time2)
        self.assertEqual(data["indoor"][0]["temperature"], 22.1)
        self.assertEqual(data["indoor"][0]["humidity"], 44.5)

    def test_indoor_data_migration(self):
        # Create a dummy data.jsonl file
        dummy_indoor_records = [
            {"time": 1782506263, "temperature": 27.81, "humidity": 47.33},
            {"time": 1782506312, "temperature": 27.79, "humidity": 47.44},
        ]
        
        db.OLD_INDOOR_DATA_FILE = "test_data.jsonl"
        
        # Cleanup any pre-existing test files
        for f in ["test_data.jsonl", "test_data.jsonl.bak"]:
            if os.path.exists(f):
                os.remove(f)

        with open("test_data.jsonl", "w", encoding="utf-8") as f:
            for r in dummy_indoor_records:
                f.write(json.dumps(r) + "\n")

        # Run migration manually
        db.migrate_old_indoor_data()

        # Assert old file is renamed to test_data.jsonl.bak
        self.assertFalse(os.path.exists("test_data.jsonl"))
        self.assertTrue(os.path.exists("test_data.jsonl.bak"))

        # Assert data is in SQLite db
        with db.get_db() as conn:
            rows = conn.execute("SELECT * FROM indoor_sensor_data ORDER BY time ASC").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["temperature"], 27.81)
            self.assertEqual(rows[0]["humidity"], 47.33)
            # Check ISO format string matches timestamp conversion
            expected_time = datetime.fromtimestamp(1782506263).isoformat()
            self.assertEqual(rows[0]["time"], expected_time)

        # Cleanup test specific files
        for f in ["test_data.jsonl", "test_data.jsonl.bak"]:
            if os.path.exists(f):
                os.remove(f)

    def test_dynamic_aggregation_and_zoom(self):
        # Seed several indoor records spanning 50 minutes (3000 seconds)
        base_time = datetime(2026, 8, 20, 10, 0, 0)
        times = [
            (base_time.replace(minute=0)).isoformat(), # 10:00:00
            (base_time.replace(minute=10)).isoformat(), # 10:10:00
            (base_time.replace(minute=20)).isoformat(), # 10:20:00
            (base_time.replace(minute=30)).isoformat(), # 10:30:00
            (base_time.replace(minute=40)).isoformat(), # 10:40:00
            (base_time.replace(minute=50)).isoformat(), # 10:50:00
        ]
        
        with db.get_db() as conn:
            for idx, t in enumerate(times):
                conn.execute(
                    "INSERT INTO indoor_sensor_data (time, temperature, humidity) VALUES (?, ?, ?)",
                    (t, 20.0 + idx, 50.0 + idx)
                )
            conn.commit()

        # Test Case 1: High zoom level (samples=100)
        # duration = 3000s, samples = 100 -> interval = 30s.
        # Since interval <= 30, it should return RAW (unaggregated) data (6 records).
        api_response_zoom = self.app_client.get(f"/api/data?start={times[0]}&end={times[-1]}&samples=100")
        self.assertEqual(api_response_zoom.status_code, 200)
        data_zoom = json.loads(api_response_zoom.data.decode("utf-8"))
        self.assertEqual(len(data_zoom["indoor"]), 6)
        # Verify it has original unrounded times (e.g. including minutes)
        self.assertEqual(data_zoom["indoor"][0]["time"], times[0])

        # Test Case 2: Low zoom level / zoomed out (samples=10)
        # duration = 3000s, samples = 10 -> interval = 300s (5 minutes).
        # Since interval > 30, it should run SQL aggregation.
        api_response_agg = self.app_client.get(f"/api/data?start={times[0]}&end={times[-1]}&samples=10")
        self.assertEqual(api_response_agg.status_code, 200)
        data_agg = json.loads(api_response_agg.data.decode("utf-8"))
        
        # SQL-aggregated times are rounded to nearest 300s interval and formatted as 'YYYY-MM-DD HH:MM:SS'
        # Since times are 10 minutes apart, each falls into a separate 5-minute bucket (300s is 5 min).
        # So we should still have 6 buckets, but the times are rounded/formatted.
        self.assertEqual(len(data_agg["indoor"]), 6)
        # Verify the time format is converted back and rounded
        self.assertEqual(data_agg["indoor"][0]["time"], "2026-08-20 10:00:00")


if __name__ == "__main__":
    unittest.main()
