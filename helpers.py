import os
import re
import logging
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "output"
LOG_DIR     = BASE_DIR / "logs"
STATIC_DIR  = BASE_DIR / "static"
UPLOAD_DIR  = BASE_DIR / "uploads"

for d in (OUTPUT_DIR, LOG_DIR, STATIC_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = BASE_DIR / "config.json"

def load_config() -> dict:
    """Load SMTP config from config.json, falling back to env vars."""
    import json
    defaults = {
        "smtp_server":   os.environ.get("SMTP_SERVER",   "smtp.gmail.com"),
        "smtp_port":     int(os.environ.get("SMTP_PORT", "587")),
        "sender_email":  os.environ.get("EMAIL_SENDER",   ""),
        "app_password":  os.environ.get("EMAIL_APP_PASSWORD", ""),
        "send_time":     os.environ.get("SEND_TIME", "08:00"),
        "timezone":      os.environ.get("TIMEZONE", "Asia/Kolkata"),
        "auto_send":     False,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    return defaults

def save_config(data: dict):
    
    import json
    existing = load_config()
    existing.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(existing, f, indent=2)

def get_logger(name: str = "birthday_app") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    from logging.handlers import RotatingFileHandler
    log_file = LOG_DIR / "app.log"
    fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger

logger = get_logger()

def safe_filename(value: str) -> str:
    
    return re.sub(r"[^\w\-]", "_", value).strip("_") or "user"

def parse_dob(dob_str: str):
    
    if not dob_str:
        return None
    dob_str = dob_str.strip()
    formats = [
        "%d-%m-%Y", "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(dob_str, fmt).date()
        except ValueError:
            continue

    parts = re.findall(r"\d+", dob_str)
    if len(parts) >= 2:
        a, b = int(parts[0]), int(parts[1])
        year = int(parts[2]) if len(parts) >= 3 else 2000
        if year < 100:
            year += 2000
        day, month = (a, b) if a > 12 else (b, a) if b > 12 else (a, b)
        try:
            return datetime(year=year, month=month, day=day).date()
        except ValueError:
            return None
    return None

def validate_email(email: str) -> bool:
    
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))

def today_in_tz(timezone: str = "Asia/Kolkata"):
    
    if ZoneInfo:
        return datetime.now(tz=ZoneInfo(timezone)).date()
    return datetime.now().date()
