from helpers import load_config, save_config, logger

_scheduler = None


def _run_daily_job():
    
    from matcher import get_matches
    from sender import send_all

    logger.info("=== Scheduled birthday run starting ===")
    config = load_config()

    try:
        csv_path = config.get("csv_path", "data.csv")
        result   = get_matches(csv_path)
        matches  = result["matches"]

        if not matches:
            logger.info("Scheduled run: no birthdays today.")
            return

        send_result = send_all(matches)
        sent    = len(send_result.get("sent", []))
        failed  = len(send_result.get("failed", []))
        logger.info(f"Scheduled run complete — {sent} sent, {failed} failed.")

        
        _notify_admin(config, send_result)

    except Exception as e:
        logger.error(f"Scheduled run failed: {e}")


def _notify_admin(config: dict, result: dict):
    import smtplib
    from email.message import EmailMessage

    sender = config.get("sender_email", "")
    if not sender or not config.get("app_password"):
        return

    sent_names    = [r["name"] for r in result.get("sent", [])]
    failed_names  = [r["name"] for r in result.get("failed", [])]

    body = f"Birthday run summary:\n\n"
    body += f"✅ Sent ({len(sent_names)}): {', '.join(sent_names) or 'none'}\n"
    body += f"❌ Failed ({len(failed_names)}): {', '.join(failed_names) or 'none'}\n"

    msg = EmailMessage()
    msg["From"]    = sender
    msg["To"]      = sender
    msg["Subject"] = "🎂 Birthday Wishes — Daily Run Summary"
    msg.set_content(body)

    try:
        with smtplib.SMTP(config["smtp_server"], int(config["smtp_port"])) as smtp:
            smtp.starttls()
            smtp.login(sender, config["app_password"])
            smtp.send_message(msg)
        logger.info("Admin summary email sent.")
    except Exception as e:
        logger.warning(f"Could not send admin summary: {e}")


def start_scheduler():
    
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("APScheduler not installed. Run: pip install apscheduler")
        return

    config    = load_config()
    send_time = config.get("send_time", "08:00")
    timezone  = config.get("timezone", "Asia/Kolkata")
    auto_send = config.get("auto_send", False)

    _scheduler = BackgroundScheduler(timezone=timezone)

    if auto_send:
        hour, minute = map(int, send_time.split(":"))
        _scheduler.add_job(
            _run_daily_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="birthday_daily",
            replace_existing=True,
        )
        logger.info(f"Scheduler started — auto-send at {send_time} ({timezone})")
    else:
        logger.info("Scheduler loaded — auto-send is disabled.")

    _scheduler.start()
    return _scheduler


def update_schedule(send_time: str = None, auto_send: bool = None, timezone: str = None):
   
    global _scheduler
    config = load_config()

    updates = {}
    if send_time  is not None: updates["send_time"]  = send_time
    if auto_send  is not None: updates["auto_send"]  = auto_send
    if timezone   is not None: updates["timezone"]   = timezone
    save_config(updates)
    config.update(updates)

    
    if _scheduler:
        try:
            from apscheduler.triggers.cron import CronTrigger
            if config.get("auto_send"):
                h, m = map(int, config["send_time"].split(":"))
                _scheduler.add_job(
                    _run_daily_job,
                    trigger=CronTrigger(hour=h, minute=m),
                    id="birthday_daily",
                    replace_existing=True,
                )
            else:
                if _scheduler.get_job("birthday_daily"):
                    _scheduler.remove_job("birthday_daily")
        except Exception as e:
            logger.error(f"Failed to reschedule: {e}")

    return config


def get_next_run() -> str:
    
    if _scheduler:
        job = _scheduler.get_job("birthday_daily")
        if job and job.next_run_time:
            return job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")
    return "Not scheduled"
