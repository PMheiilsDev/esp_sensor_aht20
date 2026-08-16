import json
import os

from flask import Flask, render_template, jsonify, request, make_response
from datetime import datetime

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

    dates = sorted({
        item["time"].date().isoformat()
        for item in data
    })

    # Last two available calendar days
    last_days = dates[-2:]

    return render_template(
        "index.html",
        min_date=dates[0],
        max_date=dates[-1],
        default_start=last_days[0],
        default_end=last_days[-1],
    )


@app.route("/api/data")
def api_data():

    # --------------------------------------------------------
    # Check whether data.txt changed
    # --------------------------------------------------------

    stat = os.stat(DATA_FILE)

    # Nanoseconds gives us much better resolution than
    # st_mtime on systems with coarse filesystem timestamps.
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
        data = [
            item for item in data
            if item["time"].date().isoformat() >= start
        ]

    if end:
        data = [
            item for item in data
            if item["time"].date().isoformat() <= end
        ]


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