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
        row_outdoor = conn.execute("SELECT MIN(time) as min_t, MAX(time) as max_t FROM sensor_data").fetchone()
        row_indoor = conn.execute("SELECT MIN(time) as min_t, MAX(time) as max_t FROM indoor_sensor_data").fetchone()

    min_t_candidates = []
    max_t_candidates = []

    if row_outdoor and row_outdoor["min_t"]:
        min_t_candidates.append(row_outdoor["min_t"])
    if row_outdoor and row_outdoor["max_t"]:
        max_t_candidates.append(row_outdoor["max_t"])

    if row_indoor and row_indoor["min_t"]:
        min_t_candidates.append(row_indoor["min_t"])
    if row_indoor and row_indoor["max_t"]:
        max_t_candidates.append(row_indoor["max_t"])

    if not min_t_candidates or not max_t_candidates:
        return render_template(
            "index.html",
            min_date=None,
            max_date=None,
            default_start="",
            default_end="",
        )

    min_time = datetime.fromisoformat(min(min_t_candidates))
    max_time = datetime.fromisoformat(max(max_t_candidates))

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

    query_outdoor = "SELECT time, temperature, humidity, vbat, power_save FROM sensor_data"
    query_indoor = "SELECT time, temperature, humidity FROM indoor_sensor_data"

    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)
        query_outdoor += where_clause
        query_indoor += where_clause

    query_outdoor += " ORDER BY time"
    query_indoor += " ORDER BY time"

    with get_db() as conn:
        rows_outdoor = conn.execute(query_outdoor, params).fetchall()
        rows_indoor = conn.execute(query_indoor, params).fetchall()

    result_outdoor = [
        {
            "time": row["time"],
            "temperature": row["temperature"],
            "humidity": row["humidity"],
            "vbat": row["vbat"],
            "power_save": bool(row["power_save"]),
        }
        for row in rows_outdoor
    ]

    result_indoor = [
        {
            "time": row["time"],
            "temperature": row["temperature"],
            "humidity": row["humidity"],
        }
        for row in rows_indoor
    ]

    result = {
        "outdoor": result_outdoor,
        "indoor": result_indoor
    }

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