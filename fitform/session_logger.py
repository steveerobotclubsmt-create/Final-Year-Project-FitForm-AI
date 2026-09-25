"""Saves each session to a CSV file and serves the log over Wi-Fi with Flask.

Endpoints (replace <pi-ip> with the Raspberry Pi's IP address):
  http://<pi-ip>:5000/                -> short help page
  http://<pi-ip>:5000/sessions        -> all sessions as JSON
  http://<pi-ip>:5000/sessions.csv    -> download the CSV file
"""

import csv
import logging
import os
import threading

from . import config

FIELDS = [
    "timestamp", "exercise", "reps_right", "reps_left", "reps_total",
    "attempted_total", "form_accuracy_pct", "duration_s", "calories_kcal",
    "avg_rep_speed_s",
]


class SessionLogger:
    def __init__(self, log_dir=config.LOG_DIR, filename=config.CSV_FILENAME):
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.abspath(os.path.join(log_dir, filename))

    def save(self, summary):
        new_file = not os.path.exists(self.path)
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow({k: summary.get(k, "") for k in FIELDS})
        print(f"[LOG] Session saved to {self.path}")

    def read_all(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def create_app(logger):
    from flask import Flask, jsonify, send_file

    app = Flask(__name__)

    @app.route("/")
    def index():
        return ("<h2>FitForm AI</h2>"
                "<p><a href='/sessions'>/sessions</a> - session history (JSON)</p>"
                "<p><a href='/sessions.csv'>/sessions.csv</a> - download CSV</p>")

    @app.route("/sessions")
    def sessions():
        return jsonify(logger.read_all())

    @app.route("/sessions.csv")
    def sessions_csv():
        if not os.path.exists(logger.path):
            return "No sessions logged yet.", 404
        return send_file(logger.path, mimetype="text/csv", as_attachment=True,
                         download_name=os.path.basename(logger.path))

    return app


def start_server(logger, host=config.FLASK_HOST, port=config.FLASK_PORT):
    """Runs Flask in a background thread so it does not block the camera loop."""
    app = create_app(logger)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    print(f"[FLASK] Session log available at http://<this-device-ip>:{port}/sessions")
    return thread
