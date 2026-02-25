import os
import shutil
import time
import base64
from pathlib import Path
from datetime import date
from email.message import EmailMessage
from email.utils import make_msgid

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from helpers import (
    OUTPUT_DIR, safe_filename, load_config, logger,
    LOG_DIR
)

# ==============================
# GMAIL API CONFIG
# ==============================
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_FILE = "token.json"

SENT_LOG = LOG_DIR / "sent_today.log"


# ==============================
# DUPLICATE GUARD
# ==============================
def _already_sent_today(email: str) -> bool:
    today = date.today().isoformat()
    if not SENT_LOG.exists():
        return False
    with open(SENT_LOG) as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) == 2 and parts[0] == today and parts[1] == email:
                return True
    return False


def _mark_sent_today(email: str):
    today = date.today().isoformat()
    with open(SENT_LOG, "a") as f:
        f.write(f"{today}|{email}\n")


# ==============================
# CARD RENDERING (UNCHANGED)
# ==============================
def _render_card(name: str, rollnumber: str, template_html: str) -> tuple[Path, Path]:
    from playwright.sync_api import sync_playwright, Error as PWError

    fname      = safe_filename(rollnumber or name)
    html_path  = OUTPUT_DIR / f"{fname}.html"
    image_path = OUTPUT_DIR / f"{fname}.png"

    personalised = template_html.replace("{{name}}", name)
    html_path.write_text(personalised, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(
                viewport={"width": 1000, "height": 600},
                device_scale_factor=2,
            )
            page = ctx.new_page()
            page.goto(html_path.absolute().as_uri(), wait_until="networkidle")
            page.wait_for_timeout(400)
            page.screenshot(path=str(image_path), full_page=True)
            page.close()
            browser.close()
    except PWError as e:
        raise RuntimeError(f"Playwright error for '{name}': {e}")

    return html_path, image_path


# ==============================
# EMAIL BUILD (UNCHANGED)
# ==============================
def _build_email(sender: str, name: str, to_email: str, image_path: Path) -> EmailMessage:
    cid = make_msgid()
    msg = EmailMessage()
    msg["From"]    = sender
    msg["To"]      = to_email
    msg["Subject"] = f"Happy Birthday {name} 🎉"

    msg.set_content(f"Happy Birthday {name}!\nWishing you a wonderful day.")

    msg.add_alternative(
        f"""<html>
          <body style="margin:0;text-align:center;background:#f2f2f2;padding:20px;">
            <img src="cid:{cid[1:-1]}" style="max-width:100%;height:auto;border-radius:12px;">
          </body>
        </html>""",
        subtype="html",
    )

    with open(image_path, "rb") as img:
        msg.get_payload()[1].add_related(
            img.read(),
            maintype="image",
            subtype="png",
            cid=cid,
            filename="Birthday_Card.png",
        )

    return msg


# ==============================
# GMAIL API SERVICE
# ==============================
def _get_gmail_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError("token.json missing or invalid")

    return build("gmail", "v1", credentials=creds)


def _send_via_gmail_api(msg: EmailMessage):
    service = _get_gmail_service()

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()


# ==============================
# SEND ONE EMAIL (MODIFIED)
# ==============================
def _send_one(sender: str, match: dict,
              template_html: str, max_retries: int = 3) -> dict:

    name       = match["name"]
    email      = match["email"]
    rollnumber = match["rollnumber"]

    # Render card
    try:
        _, image_path = _render_card(name, rollnumber, template_html)
    except Exception as e:
        logger.error(f"[RENDER-FAIL] {name}: {e}")
        return {"name": name, "email": email, "status": "failed", "error": str(e)}

    msg = _build_email(sender, name, email, image_path)

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            _send_via_gmail_api(msg)
            _mark_sent_today(email)
            logger.info(f"[SENT] {name} <{email}> (attempt {attempt})")
            return {"name": name, "email": email, "status": "sent", "error": ""}
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[RETRY {attempt}/{max_retries}] {name}: {e}")
            time.sleep(2 ** attempt)

    logger.error(f"[FAIL] {name} <{email}> after {max_retries} attempts")
    return {"name": name, "email": email, "status": "failed", "error": last_error}


# ==============================
# SEND ALL (MODIFIED)
# ==============================
def send_all(matches: list, template_html: str = None,
             progress_callback=None) -> dict:

    if not matches:
        return {"sent": [], "failed": [], "skipped": [], "total": 0}

    config = load_config()
    sender_email = config["sender_email"]

    if not sender_email:
        raise ValueError("Sender email not configured")

    if template_html is None:
        template_path = Path("template.html")
        if not template_path.exists():
            raise FileNotFoundError("template.html not found.")
        template_html = template_path.read_text(encoding="utf-8")

    results = {"sent": [], "failed": [], "skipped": [], "total": len(matches)}

    for i, match in enumerate(matches, start=1):
        result = _send_one(sender_email, match, template_html)
        status = result["status"]
        results.setdefault(status, []).append(result)

        if progress_callback:
            progress_callback(i, len(matches), result)

    if OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(exist_ok=True)

    logger.info(
        f"Run complete — {len(results.get('sent', []))} sent, "
        f"{len(results.get('failed', []))} failed."
    )

    return results
