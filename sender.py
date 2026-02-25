import os
import time
import base64
import shutil
import requests
from pathlib import Path
from datetime import date

from helpers import (
    OUTPUT_DIR, safe_filename, load_config, logger,
    LOG_DIR
)

# ==============================
# ElasticEmail API CONFIG
# ==============================
#ELASTIC_API_KEY = "06B62CE07959B5E168189BBC91EF3F53EB5DBFBD163351BDA41A5B29ABF00EB7687954E3D619BC74687D642E7F450966"  # your API key
ELASTIC_API_KEY = os.environ.get("ELASTIC_API_KEY")
ELASTIC_FROM = os.environ.get("ELASTIC_FROM")    # verified sender email
ELASTIC_API_URL = "https://api.elasticemail.com/v4/emails"


from helpers import logger
import os


SENT_LOG = LOG_DIR / "sent_today.log"

# Ensure OUTPUT_DIR exists
if not OUTPUT_DIR.exists():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
# PLAYWRIGHT CARD RENDER
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
            browser = p.chromium.launch(headless=True)  # headless for servers
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
# IMAGE → BASE64
# ==============================
def _image_to_base64(image_path: Path) -> str:
    with open(image_path, "rb") as img:
        return base64.b64encode(img.read()).decode()


# ==============================
# HTML BUILDER
# ==============================
def _build_html(name: str, image_b64: str) -> str:
    return f"""
    <html>
      <body style="margin:0;text-align:center;background:#f2f2f2;padding:20px;">
        <img
          src="data:image/png;base64,{image_b64}"
          style="max-width:100%;height:auto;border-radius:12px;"
        >
      </body>
    </html>
    """


# ==============================
# SEND VIA ELASTICEMAIL API
# ==============================
def _send_via_elastic_api(name: str, to_email: str, html: str):
    if not ELASTIC_API_KEY or not ELASTIC_FROM:
        raise ValueError("ElasticEmail API key or FROM email missing")

    payload = {
        "Recipients": {
            "To": [to_email]
        },
        "Content": {
            "From": {
                "Email": ELASTIC_FROM,
                "Name": "Birthday Bot"
            },
            "Subject": f"Happy Birthday {name} 🎉",
            "Body": [
                {
                    "ContentType": "PlainText",
                    "Content": f"Happy Birthday {name}! 🎉\n\nWishing you a wonderful day!"
                },
                {
                    "ContentType": "HTML",
                    "Content": html
                }
            ]
        }
    }

    headers = {
        "X-ElasticEmail-ApiKey": ELASTIC_API_KEY,
        "Content-Type": "application/json"
    }

    r = requests.post(
        "https://api.elasticemail.com/v4/emails",
        json=payload,
        headers=headers,
        timeout=20
    )
    logger.error(f"ElasticEmail response: {r.status_code} {r.text}")

    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"{r.status_code} | {r.text}")
# ==============================
# SINGLE SEND
# ==============================
def _send_one(match: dict, template_html: str, max_retries: int = 3) -> dict:
    name       = match["name"]
    email      = match["email"]
    rollnumber = match.get("rollnumber", "")
    """
    # Skip duplicate sends for today
    if _already_sent_today(email):
        logger.info(f"[SKIP-DUP] {name} <{email}> already sent today.")
        return {"name": name, "email": email, "status": "skipped_duplicate", "error": ""}
    """
    try:
        _, image_path = _render_card(name, rollnumber, template_html)
        image_b64 = _image_to_base64(image_path)
        html = _build_html(name, image_b64)
    except Exception as e:
        logger.error(f"[RENDER-FAIL] {name}: {e}")
        return {"name": name, "email": email, "status": "failed", "error": str(e)}

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            _send_via_elastic_api(name, email, html)
            _mark_sent_today(email)
            logger.info(f"[SENT] {name} <{email}> (attempt {attempt})")
            return {"name": name, "email": email, "status": "sent", "error": ""}
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[RETRY {attempt}/{max_retries}] {name}: {e}")
            time.sleep(2 ** attempt)

    logger.error(f"[FAIL] {name} <{email}> after {max_retries} attempts: {last_error}")
    return {"name": name, "email": email, "status": "failed", "error": last_error}


# ==============================
# SEND ALL
# ==============================
def send_all(matches: list, template_html: str = None, progress_callback=None) -> dict:

    if not matches:
        return {"sent": [], "failed": [], "skipped": [], "total": 0}

    if template_html is None:
        template_path = Path("template.html")
        if not template_path.exists():
            raise FileNotFoundError("template.html not found.")
        template_html = template_path.read_text(encoding="utf-8")

    results = {"sent": [], "failed": [], "skipped": [], "total": len(matches)}

    for i, match in enumerate(matches, start=1):
        result = _send_one(match, template_html)
        status = result["status"]
        # Normalize skipped status key
        if status == "skipped_duplicate":
            status = "skipped"
        results.setdefault(status, []).append(result)

        if progress_callback:
            progress_callback(i, len(matches), result)

    logger.info(
        f"Run complete — "
        f"{len(results.get('sent', []))} sent, "
        f"{len(results.get('failed', []))} failed, "
        f"{len(results.get('skipped', []))} skipped."
    )

    return results
