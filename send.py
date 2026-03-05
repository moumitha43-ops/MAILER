import os
import time
import json
import base64
from pathlib import Path
from datetime import date
from email.message import EmailMessage
from email.utils import make_msgid

from dotenv import load_dotenv
load_dotenv()

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from helpers import OUTPUT_DIR, safe_filename, load_config, logger, LOG_DIR

# ==============================
# CONFIG
# ==============================
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
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
            d, e = line.strip().split("|")
            if d == today and e == email:
                return True
    return False


def _mark_sent_today(email: str):
    today = date.today().isoformat()
    LOG_DIR.mkdir(exist_ok=True)
    with open(SENT_LOG, "a") as f:
        f.write(f"{today}|{email}\n")


# ==============================
# CARD RENDER
# ==============================
def _render_card(name: str, rollnumber: str, template_html: str):
    from playwright.sync_api import sync_playwright

    fname = safe_filename(rollnumber or name)
    html_path = OUTPUT_DIR / f"{fname}.html"
    image_path = OUTPUT_DIR / f"{fname}.png"

    personalised = template_html.replace("{{name}}", name)
    html_path.write_text(personalised, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1000, "height": 600},
            device_scale_factor=2,
        )
        page = ctx.new_page()
        page.goto(html_path.absolute().as_uri())
        page.wait_for_timeout(400)
        page.screenshot(path=str(image_path), full_page=True)
        browser.close()

    return image_path


# ==============================
# EMAIL BUILD
# ==============================
def _build_email(sender: str, name: str, to_email: str, image_path: Path):
    cid = make_msgid()

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = f"Happy Birthday {name} 🎉"

    msg.set_content(f"Happy Birthday {name}!")

    msg.add_alternative(
        f"""
        <html>
          <body style="text-align:center;background:#f2f2f2;padding:20px;">
            <img src="cid:{cid[1:-1]}" 
                 style="max-width:100%;border-radius:12px;">
          </body>
        </html>
        """,
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
# GMAIL AUTH (ENV BASED)
# ==============================
def _get_gmail_service():
    token_json = os.getenv("GOOGLE_TOKEN_JSON")

    if not token_json:
        raise RuntimeError("GOOGLE_TOKEN_JSON env variable missing")

    token_data = json.loads(token_json)

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("gmail", "v1", credentials=creds)


def _send_via_gmail_api(msg: EmailMessage):
    service = _get_gmail_service()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()


# ==============================
# SEND ONE
# ==============================
def _send_one(sender: str, person: dict, template_html: str):
    name = person["name"]
    email = person["email"]
    rollnumber = person.get("rollnumber", "")

    if _already_sent_today(email):
        return {"name": name, "status": "skipped"}

    try:
        image_path = _render_card(name, rollnumber, template_html)
        msg = _build_email(sender, name, email, image_path)
        _send_via_gmail_api(msg)
        _mark_sent_today(email)
        return {"name": name, "status": "sent"}
    except Exception as e:
        return {"name": name, "status": "failed", "error": str(e)}


# ==============================
# SEND ALL
# ==============================
def send_all(matches: list):
    config = load_config()
    sender_email = config.get("sender_email")

    template_html = Path("template.html").read_text(encoding="utf-8")

    results = []

    for person in matches:
        result = _send_one(sender_email, person, template_html)
        results.append(result)

    return results
