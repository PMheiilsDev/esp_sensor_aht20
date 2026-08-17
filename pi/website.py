import json
import os

from flask import Flask, render_template, jsonify, request, make_response
from datetime import datetime, timedelta

app = Flask(__name__)

DATA_FILE = "data.txt"


def load_data():
    data = []

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Skipping line {line_number}: {e}")
                continue

            try:
                data.append({
                    "time": datetime.fromisoformat(item["time"]),
                    "temperature": float(item["temperature"]),
                    "vbat": float(item["vbat"]),
                    "power_save": bool(item["power_save"]),
                })
            except (KeyError, ValueError, TypeError) as e:
                print(f"Skipping line {line_number}: {e}")

    data.sort(key=lambda x: x["time"])

    return data


@app.route("/")
def index():
    data = load_data()

    if not data:
        return render_template(
            "index.html",
            min_date=None,
            max_date=None,
            default_start="",
            default_end="",
        )

    # Full available data range
    min_time = data[0]["time"]
    max_time = data[-1]["time"]

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
    # Check whether data.txt changed
    # --------------------------------------------------------

    stat = os.stat(DATA_FILE)

    version = f"{stat.st_mtime_ns}-{stat.st_size}"

    client_version = request.headers.get("If-None-Match")

    if client_version == version:
        response = make_response("", 304)
        response.headers["ETag"] = version
        response.headers["Cache-Control"] = "no-cache"
        return response

    # --------------------------------------------------------
    # File changed -> load data
    # --------------------------------------------------------

    data = load_data()

    start = request.args.get("start")
    end = request.args.get("end")

    if start:
        try:
            start_time = datetime.fromisoformat(start)
            data = [
                item for item in data
                if item["time"] >= start_time
            ]
        except ValueError:
            return jsonify({"error": "Invalid start datetime"}), 400

    if end:
        try:
            end_time = datetime.fromisoformat(end)
            data = [
                item for item in data
                if item["time"] <= end_time
            ]
        except ValueError:
            return jsonify({"error": "Invalid end datetime"}), 400

    result = [
        {
            "time": item["time"].isoformat(),
            "temperature": item["temperature"],
            "vbat": item["vbat"],
            "power_save": item["power_save"],
        }
        for item in data
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