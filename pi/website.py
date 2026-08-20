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

    try:
        samples = int(request.args.get("samples", 500))
    except ValueError:
        samples = 500

    start_dt = None
    end_dt = None

    if start:
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            pass

    if end:
        try:
            end_dt = datetime.fromisoformat(end)
        except ValueError:
            pass
    else:
        # If no end is provided, get the max time from database
        with get_db() as conn:
            row_out = conn.execute("SELECT MAX(time) as max_t FROM sensor_data").fetchone()
            row_in = conn.execute("SELECT MAX(time) as max_t FROM indoor_sensor_data").fetchone()
        candidates = []
        if row_out and row_out["max_t"]:
            candidates.append(row_out["max_t"])
        if row_in and row_in["max_t"]:
            candidates.append(row_in["max_t"])
        if candidates:
            try:
                end_dt = datetime.fromisoformat(max(candidates))
            except ValueError:
                end_dt = datetime.now()
        else:
            end_dt = datetime.now()

    if not start_dt:
        with get_db() as conn:
            row_out = conn.execute("SELECT MIN(time) as min_t FROM sensor_data").fetchone()
            row_in = conn.execute("SELECT MIN(time) as min_t FROM indoor_sensor_data").fetchone()
        candidates = []
        if row_out and row_out["min_t"]:
            candidates.append(row_out["min_t"])
        if row_in and row_in["min_t"]:
            candidates.append(row_in["min_t"])
        if candidates:
            try:
                start_dt = datetime.fromisoformat(min(candidates))
            except ValueError:
                start_dt = datetime.now()
        else:
            start_dt = datetime.now()

    duration_seconds = (end_dt - start_dt).total_seconds() if start_dt and end_dt else 0
    interval = int(duration_seconds / samples) if samples > 0 else 0

    if interval <= 30:
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
            query_outdoor += where_clause
            query_indoor += where_clause

        query_outdoor += " ORDER BY time"
        query_indoor += " ORDER BY time"

        with get_db() as conn:
            rows_outdoor = conn.execute(query_outdoor, params).fetchall()
            rows_indoor = conn.execute(query_indoor, params).fetchall()
    else:
        query_outdoor = """
            SELECT 
                datetime((strftime('%s', time) / ?) * ?, 'unixepoch') AS time,
                ROUND(AVG(temperature), 2) AS temperature,
                ROUND(AVG(humidity), 2) AS humidity,
                ROUND(AVG(vbat), 3) AS vbat,
                MAX(power_save) AS power_save
            FROM sensor_data
        """
        query_indoor = """
            SELECT 
                datetime((strftime('%s', time) / ?) * ?, 'unixepoch') AS time,
                ROUND(AVG(temperature), 2) AS temperature,
                ROUND(AVG(humidity), 2) AS humidity
            FROM indoor_sensor_data
        """

        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)

        query_outdoor += where_clause + " GROUP BY time ORDER BY time"
        query_indoor += where_clause + " GROUP BY time ORDER BY time"

        params_outdoor = [interval, interval] + params
        params_indoor = [interval, interval] + params

        with get_db() as conn:
            rows_outdoor = conn.execute(query_outdoor, params_outdoor).fetchall()
            rows_indoor = conn.execute(query_indoor, params_indoor).fetchall()

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