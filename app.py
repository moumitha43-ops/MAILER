"""
app.py — Flask web application for Birthday Wishes automation.
Run: python app.py
Then open http://localhost:5000 in your browser.
"""

import os
import json
import threading
from pathlib import Path
from datetime import datetime
from flask import (Flask, request, jsonify, render_template,
                   send_from_directory)
from werkzeug.utils import secure_filename

from helpers import load_config, save_config, logger, UPLOAD_DIR, LOG_DIR
from matcher import get_matches, validate_csv
from sendapi  import send_all
from scheduler import start_scheduler, update_schedule, get_next_run

# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 1024 ** 3   # 1 GB upload limit

ALLOWED_EXTENSIONS = {"csv"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# In-memory job state (simple; upgrade to Redis for multi-worker)
_job_state = {"running": False, "progress": 0, "total": 0, "results": []}

# ──────────────────────────────────────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ──────────────────────────────────────────────────────────────────────────────
# CSV endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/csv/upload", methods=["POST"])
def upload_csv():
    """Upload a new data CSV."""
    if "file" not in request.files:
        return jsonify({"error": "No file part in request."}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No file selected."}), 400
    if not allowed_file(f.filename):
        return jsonify({"error": "Only .csv files are accepted."}), 400

    filename = secure_filename(f.filename)
    dest     = UPLOAD_DIR / filename
    f.save(str(dest))
    save_config({"csv_path": str(dest)})
    logger.info(f"CSV uploaded: {dest}")

    # Validate immediately
    try:
        validation = validate_csv(str(dest))
    except Exception as e:
        return jsonify({"error": str(e)}), 422

    return jsonify({
        "message":  "CSV uploaded successfully.",
        "filename": filename,
        "validation": validation,
    })


@app.route("/api/csv/validate", methods=["GET"])
def validate_current_csv():
    """Validate the currently loaded CSV and return a preview."""
    config   = load_config()
    csv_path = config.get("csv_path", "data.csv")
    try:
        result = validate_csv(csv_path)
        return jsonify(result)
    except FileNotFoundError:
        return jsonify({"error": f"No CSV loaded yet. Please upload one."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────────────────
# Birthday match / send endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/matches", methods=["GET"])
def today_matches():
    """Return today's birthday matches."""
    config   = load_config()
    csv_path = config.get("csv_path", "data.csv")
    try:
        result = get_matches(csv_path)
        return jsonify(result)
    except FileNotFoundError:
        return jsonify({"error": "CSV not found. Please upload a file."}), 404
    except Exception as e:
        logger.error(f"/api/matches error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/send", methods=["POST"])
def send_emails():
    """
    Trigger email sending.
    Runs in a background thread; poll /api/send/status for progress.
    """
    global _job_state
    if _job_state["running"]:
        return jsonify({"error": "A send job is already running."}), 409

    config   = load_config()
    csv_path = config.get("csv_path", "data.csv")

    try:
        match_result = get_matches(csv_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    matches = match_result["matches"]
    if not matches:
        return jsonify({"message": "No birthdays today. Nothing to send.", "sent": 0})

    # Load template
    template_path = Path("template.html")
    if not template_path.exists():
        return jsonify({"error": "template.html not found."}), 500
    template_html = template_path.read_text(encoding="utf-8")

    _job_state = {"running": True, "progress": 0, "total": len(matches), "results": []}

    def progress_cb(current, total, result):
        _job_state["progress"] = current
        _job_state["results"].append(result)

    def run():
        global _job_state
        try:
            send_all(matches, template_html=template_html, progress_callback=progress_cb)
        except Exception as e:
            logger.error(f"Send job error: {e}")
            _job_state["error"] = str(e)
        finally:
            _job_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"message": f"Sending to {len(matches)} person(s)…", "total": len(matches)})


@app.route("/api/send/status", methods=["GET"])
def send_status():
    """Poll this endpoint to get live progress of an ongoing send job."""
    return jsonify(_job_state)


# ──────────────────────────────────────────────────────────────────────────────
# Settings endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def get_settings():
    config = load_config()
    # Never expose the password to the frontend
    safe   = {k: v for k, v in config.items() if k != "app_password"}
    safe["password_set"] = bool(config.get("app_password"))
    safe["next_run"]     = get_next_run()
    return jsonify(safe)


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json(silent=True) or {}
    allowed = {"smtp_server", "smtp_port", "sender_email", "app_password",
               "send_time", "timezone", "auto_send"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields provided."}), 400

    save_config(updates)

    # Apply scheduler changes live
    if "send_time" in updates or "auto_send" in updates or "timezone" in updates:
        update_schedule(
            send_time = updates.get("send_time"),
            auto_send = updates.get("auto_send"),
            timezone  = updates.get("timezone"),
        )

    logger.info(f"Settings updated: {[k for k in updates if k != 'app_password']}")
    return jsonify({"message": "Settings saved.", "next_run": get_next_run()})


# ──────────────────────────────────────────────────────────────────────────────
# Template management
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/template", methods=["GET"])
def get_template():
    p = Path("template.html")
    if not p.exists():
        return jsonify({"html": ""}), 200
    return jsonify({"html": p.read_text(encoding="utf-8")})


@app.route("/api/template", methods=["POST"])
def save_template():
    data = request.get_json(silent=True) or {}
    html = data.get("html", "")
    if not html.strip():
        return jsonify({"error": "Template HTML cannot be empty."}), 400
    Path("template.html").write_text(html, encoding="utf-8")
    logger.info("Template saved.")
    return jsonify({"message": "Template saved."})


@app.route("/api/template/upload-image", methods=["POST"])
def upload_template_image():
    """Upload logo/signature images for the card template."""
    if "file" not in request.files:
        return jsonify({"error": "No file."}), 400
    f = request.files["file"]
    allowed_img = {"png", "jpg", "jpeg", "gif", "webp"}
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in allowed_img:
        return jsonify({"error": "Only image files allowed."}), 400

    from base64 import b64encode
    data_uri = f"data:image/{ext};base64," + b64encode(f.read()).decode()
    return jsonify({"data_uri": data_uri, "filename": secure_filename(f.filename)})


# ──────────────────────────────────────────────────────────────────────────────
# Logs
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Return last N lines of the app log for the UI log viewer."""
    n        = int(request.args.get("lines", 100))
    log_file = LOG_DIR / "app.log"
    if not log_file.exists():
        return jsonify({"lines": []})
    with open(log_file, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return jsonify({"lines": [l.rstrip() for l in lines[-n:]]})


# ──────────────────────────────────────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Birthday Wishes app on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
