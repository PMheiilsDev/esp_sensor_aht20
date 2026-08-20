import sqlite3
import os
import json
from datetime import datetime

from conf import DB_FILE

OLD_DATA_FILE = "data.txt"


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                vbat REAL NOT NULL,
                power_save INTEGER NOT NULL
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_data_time 
            ON sensor_data(time);
        """)
        conn.commit()

    migrate_old_data()


def migrate_old_data():
    if not os.path.exists(OLD_DATA_FILE):
        return

    print(f"Found old data file '{OLD_DATA_FILE}'. Starting migration to SQLite...", flush=True)

    records = []
    with open(OLD_DATA_FILE, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                time_str = item["time"]
                # Validate datetime format
                datetime.fromisoformat(time_str)
                temp = float(item["temperature"])
                hum = float(item["humidity"])
                vbat = float(item["vbat"])
                ps = 1 if bool(item["power_save"]) else 0

                records.append((time_str, temp, hum, vbat, ps))
            except Exception as e:
                print(f"Skipping line {line_number} in old data during migration: {e}", flush=True)

    if records:
        try:
            with get_db() as conn:
                conn.executemany(
                    "INSERT INTO sensor_data (time, temperature, humidity, vbat, power_save) VALUES (?, ?, ?, ?, ?)",
                    records
                )
                conn.commit()
            print(f"Successfully migrated {len(records)} records from '{OLD_DATA_FILE}' to SQLite.", flush=True)
        except Exception as e:
            print(f"Error during migration transaction: {e}", flush=True)
            return

    # Rename old file to avoid migrating again
    try:
        backup_file = OLD_DATA_FILE + ".bak"
        if os.path.exists(backup_file):
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_file = f"{OLD_DATA_FILE}.{timestamp}.bak"
        os.rename(OLD_DATA_FILE, backup_file)
        print(f"Renamed old data file to '{backup_file}'.", flush=True)
    except Exception as e:
        print(f"Failed to rename old data file: {e}", flush=True)
