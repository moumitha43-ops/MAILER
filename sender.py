import shutil
import smtplib
import time
from pathlib import Path
from datetime import date
from email.message import EmailMessage
from email.utils import make_msgid

from helpers import (
    OUTPUT_DIR, safe_filename, load_config, logger,
    LOG_DIR
)

SENT_LOG = LOG_DIR / "sent_today.log"

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
            ctx     = browser.new_context(
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
            img.read(), maintype="image", subtype="png", cid=cid,filename=f"Birthday_Card.png"
        )
    return msg


def _send_one(smtp: smtplib.SMTP, sender: str, match: dict,
              template_html: str, max_retries: int = 3) -> dict:
    
    name       = match["name"]
    email      = match["email"]
    rollnumber = match["rollnumber"]

    # Duplicate guard
    """
    if _already_sent_today(email):
        logger.info(f"[SKIP-DUP] {name} <{email}> already sent today.")
        return {"name": name, "email": email, "status": "skipped_duplicate", "error": ""}
    """
    # Render card
    try:
        _, image_path = _render_card(name, rollnumber, template_html)
    except Exception as e:
        logger.error(f"[RENDER-FAIL] {name}: {e}")
        return {"name": name, "email": email, "status": "failed", "error": str(e)}

    # Send with retries
    msg = _build_email(sender, name, email, image_path)
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            smtp.send_message(msg)
            _mark_sent_today(email)
            logger.info(f"[SENT] {name} <{email}> (attempt {attempt})")
            return {"name": name, "email": email, "status": "sent", "error": ""}
        except smtplib.SMTPException as e:
            last_error = str(e)
            logger.warning(f"[RETRY {attempt}/{max_retries}] {name}: {e}")
            time.sleep(2 ** attempt)

    logger.error(f"[FAIL] {name} <{email}> after {max_retries} attempts: {last_error}")
    return {"name": name, "email": email, "status": "failed", "error": last_error}



def send_all(matches: list, template_html: str = None,
             progress_callback=None) -> dict:
   
    if not matches:
        return {"sent": [], "failed": [], "skipped": [], "total": 0}

    config = load_config()
    smtp_server  = config["smtp_server"]
    smtp_port    = int(config["smtp_port"])
    sender_email = config["sender_email"]
    app_password = config["app_password"]

    if not sender_email or not app_password:
        raise ValueError("SMTP credentials are not configured. Go to Settings to add them.")

    # Load template
    if template_html is None:
        template_path = Path("template.html")
        if not template_path.exists():
            raise FileNotFoundError("template.html not found.")
        template_html = template_path.read_text(encoding="utf-8")

    results = {"sent": [], "failed": [], "skipped": [], "total": len(matches)}

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(sender_email, app_password)
            logger.info(f"SMTP connected as {sender_email}")

            for i, match in enumerate(matches, start=1):
                result = _send_one(smtp, sender_email, match, template_html)
                status = result["status"]
                results.setdefault(status, []).append(result)
                if status not in results:
                    results["failed"].append(result)

                if progress_callback:
                    progress_callback(i, len(matches), result)

    except smtplib.SMTPAuthenticationError:
        raise ValueError("SMTP authentication failed. Check your email and App Password in Settings.")
    except smtplib.SMTPConnectError as e:
        raise ConnectionError(f"Could not connect to SMTP server {smtp_server}:{smtp_port} — {e}")
    except Exception as e:
        logger.error(f"Unexpected SMTP error: {e}")
        raise
    finally:
        
        if OUTPUT_DIR.exists():
            #shutil.rmtree(OUTPUT_DIR)
            OUTPUT_DIR.mkdir(exist_ok=True)

    sent_n    = len(results.get("sent", []))
    failed_n  = len(results.get("failed", []))
    skipped_n = len(results.get("skipped_duplicate", []))
    logger.info(f"Run complete — {sent_n} sent, {failed_n} failed, {skipped_n} skipped.")

    return results
