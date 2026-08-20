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
    keep_raw = request.args.get("keep_raw", "true").lower() == "true"

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

    start_str = start_dt.isoformat() if start_dt else start
    end_str = end_dt.isoformat() if end_dt else end

    if interval <= 30:
        query_outdoor = "SELECT time, temperature, humidity, vbat, power_save FROM sensor_data WHERE time >= ? AND time <= ? ORDER BY time"
        query_indoor = "SELECT time, temperature, humidity FROM indoor_sensor_data WHERE time >= ? AND time <= ? ORDER BY time"

        with get_db() as conn:
            rows_outdoor = conn.execute(query_outdoor, (start_str, end_str)).fetchall()
            rows_indoor = conn.execute(query_indoor, (start_str, end_str)).fetchall()

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
    else:
        boundary_dt = end_dt - timedelta(seconds=0.1 * duration_seconds) if end_dt else datetime.now()

        raw_start_outdoor = boundary_dt
        raw_start_indoor = boundary_dt

        with get_db() as conn:
            if keep_raw:
                # Find 10th-from-last timestamp inside requested range
                row_out_10 = conn.execute(
                    "SELECT time FROM sensor_data WHERE time >= ? AND time <= ? ORDER BY time DESC LIMIT 1 OFFSET 9",
                    (start_str, end_str)
                ).fetchone()
                if row_out_10:
                    try:
                        raw_start_outdoor = min(boundary_dt, datetime.fromisoformat(row_out_10["time"]))
                    except ValueError:
                        pass

                row_in_10 = conn.execute(
                    "SELECT time FROM indoor_sensor_data WHERE time >= ? AND time <= ? ORDER BY time DESC LIMIT 1 OFFSET 9",
                    (start_str, end_str)
                ).fetchone()
                if row_in_10:
                    try:
                        raw_start_indoor = min(boundary_dt, datetime.fromisoformat(row_in_10["time"]))
                    except ValueError:
                        pass

            # Make sure raw starts do not go before start_dt
            if raw_start_outdoor < start_dt:
                raw_start_outdoor = start_dt
            if raw_start_indoor < start_dt:
                raw_start_indoor = start_dt

            raw_start_outdoor_str = raw_start_outdoor.isoformat()
            raw_start_indoor_str = raw_start_indoor.isoformat()

            # --- Query Outdoor ---
            if keep_raw and raw_start_outdoor_str > start_str:
                rows_outdoor_agg = conn.execute(
                    """
                    SELECT 
                        datetime((strftime('%s', time) / ?) * ?, 'unixepoch') AS time,
                        ROUND(AVG(temperature), 2) AS temperature,
                        ROUND(AVG(humidity), 2) AS humidity,
                        ROUND(AVG(vbat), 3) AS vbat,
                        MAX(power_save) AS power_save
                    FROM sensor_data
                    WHERE time >= ? AND time < ?
                    GROUP BY 1 ORDER BY 1
                    """,
                    (interval, interval, start_str, raw_start_outdoor_str)
                ).fetchall()

                rows_outdoor_raw = conn.execute(
                    """
                    SELECT time, temperature, humidity, vbat, power_save
                    FROM sensor_data
                    WHERE time >= ? AND time <= ?
                    ORDER BY time
                    """,
                    (raw_start_outdoor_str, end_str)
                ).fetchall()
            else:
                if keep_raw:
                    rows_outdoor_agg = []
                    rows_outdoor_raw = conn.execute(
                        "SELECT time, temperature, humidity, vbat, power_save FROM sensor_data WHERE time >= ? AND time <= ? ORDER BY time",
                        (start_str, end_str)
                    ).fetchall()
                else:
                    rows_outdoor_agg = conn.execute(
                        """
                        SELECT 
                            datetime((strftime('%s', time) / ?) * ?, 'unixepoch') AS time,
                            ROUND(AVG(temperature), 2) AS temperature,
                            ROUND(AVG(humidity), 2) AS humidity,
                            ROUND(AVG(vbat), 3) AS vbat,
                            MAX(power_save) AS power_save
                        FROM sensor_data
                        WHERE time >= ? AND time <= ?
                        GROUP BY 1 ORDER BY 1
                        """,
                        (interval, interval, start_str, end_str)
                    ).fetchall()
                    rows_outdoor_raw = []

            # --- Query Indoor ---
            if keep_raw and raw_start_indoor_str > start_str:
                rows_indoor_agg = conn.execute(
                    """
                    SELECT 
                        datetime((strftime('%s', time) / ?) * ?, 'unixepoch') AS time,
                        ROUND(AVG(temperature), 2) AS temperature,
                        ROUND(AVG(humidity), 2) AS humidity
                    FROM indoor_sensor_data
                    WHERE time >= ? AND time < ?
                    GROUP BY 1 ORDER BY 1
                    """,
                    (interval, interval, start_str, raw_start_indoor_str)
                ).fetchall()

                rows_indoor_raw = conn.execute(
                    """
                    SELECT time, temperature, humidity
                    FROM indoor_sensor_data
                    WHERE time >= ? AND time <= ?
                    ORDER BY time
                    """,
                    (raw_start_indoor_str, end_str)
                ).fetchall()
            else:
                if keep_raw:
                    rows_indoor_agg = []
                    rows_indoor_raw = conn.execute(
                        "SELECT time, temperature, humidity FROM indoor_sensor_data WHERE time >= ? AND time <= ? ORDER BY time",
                        (start_str, end_str)
                    ).fetchall()
                else:
                    rows_indoor_agg = conn.execute(
                        """
                        SELECT 
                            datetime((strftime('%s', time) / ?) * ?, 'unixepoch') AS time,
                            ROUND(AVG(temperature), 2) AS temperature,
                            ROUND(AVG(humidity), 2) AS humidity
                        FROM indoor_sensor_data
                        WHERE time >= ? AND time <= ?
                        GROUP BY 1 ORDER BY 1
                        """,
                        (interval, interval, start_str, end_str)
                    ).fetchall()
                    rows_indoor_raw = []

        result_outdoor = [
            {
                "time": row["time"],
                "temperature": row["temperature"],
                "humidity": row["humidity"],
                "vbat": row["vbat"],
                "power_save": bool(row["power_save"]),
            }
            for row in rows_outdoor_agg
        ] + [
            {
                "time": row["time"],
                "temperature": row["temperature"],
                "humidity": row["humidity"],
                "vbat": row["vbat"],
                "power_save": bool(row["power_save"]),
            }
            for row in rows_outdoor_raw
        ]

        result_indoor = [
            {
                "time": row["time"],
                "temperature": row["temperature"],
                "humidity": row["humidity"],
            }
            for row in rows_indoor_agg
        ] + [
            {
                "time": row["time"],
                "temperature": row["temperature"],
                "humidity": row["humidity"],
            }
            for row in rows_indoor_raw
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