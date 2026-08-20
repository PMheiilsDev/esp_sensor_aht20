import json
import os

from flask import Flask, render_template, jsonify, request, make_response
from datetime import datetime, timedelta

from conf import DB_FILE
from db import init_db, get_db

app = Flask(__name__)

# Initialize database (creates table/indexes & migrates old data if any)
init_db()


@app.route("/")
def index():
    with get_db() as conn:
        row = conn.execute("SELECT MIN(time) as min_t, MAX(time) as max_t FROM sensor_data").fetchone()

    if not row or row["min_t"] is None or row["max_t"] is None:
        return render_template(
            "index.html",
            min_date=None,
            max_date=None,
            default_start="",
            default_end="",
        )

    min_time = datetime.fromisoformat(row["min_t"])
    max_time = datetime.fromisoformat(row["max_t"])

    # Default: last 24 hours
    default_end = max_time
    default_start = max_time - timedelta(hours=24)

    # Don't go before the beginning of the available data
    if default_start < min_time:
        default_start = min_time

    return render_template(
        "index.html",
        min_date=min_time.strftime("%Y-%m-%dT%H:%M"),
        max_date=max_time.strftime("%Y-%m-%dT%H:%M"),
        default_start=default_start.strftime("%Y-%m-%dT%H:%M"),
        default_end=default_end.strftime("%Y-%m-%dT%H:%M"),
    )


@app.route("/api/data")
def api_data():

    # --------------------------------------------------------
    # Check whether the SQLite database changed
    # --------------------------------------------------------

    stat = os.stat(DB_FILE) if os.path.exists(DB_FILE) else None
    version = f"{stat.st_mtime_ns}-{stat.st_size}" if stat else "0-0"

    client_version = request.headers.get("If-None-Match")

    if client_version == version:
        response = make_response("", 304)
        response.headers["ETag"] = version
        response.headers["Cache-Control"] = "no-cache"
        return response

    # --------------------------------------------------------
    # Database changed -> query records
    # --------------------------------------------------------

    start = request.args.get("start")
    end = request.args.get("end")

    query = "SELECT time, temperature, humidity, vbat, power_save FROM sensor_data"
    conditions = []
    params = []

    if start:
        try:
            # Validate format
            datetime.fromisoformat(start)
            conditions.append("time >= ?")
            params.append(start)
        except ValueError:
            return jsonify({"error": "Invalid start datetime"}), 400

    if end:
        try:
            # Validate format
            datetime.fromisoformat(end)
            conditions.append("time <= ?")
            params.append(end)
        except ValueError:
            return jsonify({"error": "Invalid end datetime"}), 400

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY time"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    result = [
        {
            "time": row["time"],
            "temperature": row["temperature"],
            "humidity": row["humidity"],
            "vbat": row["vbat"],
            "power_save": bool(row["power_save"]),
        }
        for row in rows
    ]

    response = jsonify(result)

    response.headers["ETag"] = version
    response.headers["Cache-Control"] = "no-cache"

    return response


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True,
    )