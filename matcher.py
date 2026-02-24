import csv
from helpers import parse_dob, validate_email, today_in_tz, logger, load_config

def get_matches(csv_path: str = "data.csv") -> dict:
    
    config  = load_config()
    timezone = config.get("timezone", "Asia/Kolkata")
    today   = today_in_tz(timezone)
    logger.info(f"Checking birthdays for {today.isoformat()} ({timezone})")

    matches  = []
    skipped  = []
    total    = 0

    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            _check_headers(reader.fieldnames or [])

            for rownum, row in enumerate(reader, start=1):
                total += 1
                result = _process_row(row, rownum, today)
                if result["status"] == "match":
                    matches.append(result["data"])
                    logger.info(f"[MATCH]  Row {rownum}: {result['data']['name']} <{result['data']['email']}>")
                elif result["status"] == "skip":
                    skipped.append(result["data"])
                    logger.warning(f"[SKIP]   Row {rownum}: {result['data']['reason']}")
               
    except FileNotFoundError:
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    except Exception as e:
        logger.error(f"Error reading CSV: {e}")
        raise

    logger.info(f"Done — {len(matches)} match(es), {len(skipped)} skipped, {total} total rows.")
    return {"matches": matches, "skipped": skipped, "total_rows": total}


def validate_csv(csv_path: str) -> dict:
  
    valid  = []
    errors = []

    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            _check_headers(reader.fieldnames or [])

            for rownum, row in enumerate(reader, start=1):
                name      = (row.get("name") or "").strip()
                email     = (row.get("email") or "").strip()
                dob_raw   = (row.get("dob") or row.get("date_of_birth") or "").strip()
                rollno    = (row.get("rollnumber") or row.get("roll_number") or "").strip()

                issues = []
                if not name:
                    issues.append("missing name")
                if not email:
                    issues.append("missing email")
                elif not validate_email(email):
                    issues.append(f"invalid email format: '{email}'")
                if not dob_raw:
                    issues.append("missing date of birth")
                elif parse_dob(dob_raw) is None:
                    issues.append(f"unrecognised DOB format: '{dob_raw}'")

                if issues:
                    errors.append({"rownum": rownum, "name": name, "email": email,
                                   "reason": "; ".join(issues)})
                else:
                    dob_parsed = parse_dob(dob_raw)
                    valid.append({
                        "rownum":     rownum,
                        "name":       name,
                        "email":      email,
                        "dob":        dob_parsed.strftime("%d-%m-%Y"),
                        "rollnumber": rollno,
                    })

    except FileNotFoundError:
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    return {"valid": valid, "errors": errors}


def _check_headers(fieldnames: list):
    required = {"name", "email"}
    dob_cols = {"dob", "date_of_birth"}
    normalised = {f.strip().lower() for f in fieldnames}
    missing = required - normalised
    if missing:
        raise ValueError(f"CSV is missing required column(s): {missing}")
    if not (dob_cols & normalised):
        raise ValueError("CSV must have a 'dob' or 'date_of_birth' column.")


def _process_row(row: dict, rownum: int, today) -> dict:
    name    = (row.get("name") or "").strip()
    email   = (row.get("email") or "").strip()
    dob_raw = (row.get("dob") or row.get("date_of_birth") or "").strip()
    rollno  = (row.get("rollnumber") or row.get("roll_number") or "").strip()

    if not name:
        return _skip(rownum, name, email, "missing name")
    if not email or not validate_email(email):
        return _skip(rownum, name, email, f"invalid or missing email '{email}'")
    if not dob_raw:
        return _skip(rownum, name, email, "missing date of birth")

    dob = parse_dob(dob_raw)
    if not dob:
        return _skip(rownum, name, email, f"could not parse DOB '{dob_raw}'")

    if (dob.day, dob.month) == (today.day, today.month):
        return {
            "status": "match",
            "data": {"rownum": rownum, "name": name,
                     "email": email, "rollnumber": rollno}
        }

    return {"status": "no_match", "data": {}}


def _skip(rownum, name, email, reason) -> dict:
    return {"status": "skip",
            "data":   {"rownum": rownum, "name": name,
                       "email": email,  "reason": reason}}
