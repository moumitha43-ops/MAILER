# 🎂 Birthday Wishes App

Automated birthday email system with a web UI, error handling, and daily scheduling.

---

## 📁 File Structure

```
birthday_app/
├── app.py           ← Flask web server (run this)
├── helpers.py       ← Config, logging, date utilities
├── matcher.py       ← CSV parsing + birthday matching
├── sender.py        ← Email rendering + sending with retry
├── scheduler.py     ← Daily auto-send via APScheduler
├── template.html    ← Birthday card HTML (edit via UI)
├── requirements.txt ← Python dependencies
├── templates/
│   └── index.html   ← Full web dashboard UI
├── uploads/         ← Uploaded CSV files (auto-created)
├── output/          ← Temporary rendered cards (auto-cleared)
└── logs/
    ├── app.log      ← Application log
    └── sent_today.log ← Duplicate-send guard
```

---

## 🚀 Setup (First Time)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browser
playwright install chromium

# 3. Run the app
python app.py
```

Then open **http://localhost:5000** in your browser.

---

## ⚙️ First-Time Configuration (in the UI)

1. **Settings** → Enter your Gmail address + App Password
   - Get an App Password at: https://myaccount.google.com/apppasswords
   - Never use your regular Gmail password here

2. **CSV Manager** → Upload your `data.csv`
   - Required columns: `name`, `email`, `dob`, `rollnumber`
   - DOB formats accepted: `DD-MM-YYYY`, `DD/MM/YYYY`, `YYYY-MM-DD`

3. **Card Template** → Upload your logo/signature images and add them to the template

4. **Scheduler** → Enable auto-send and set the daily time

---

## 📋 CSV Format

```csv
name,email,dob,rollnumber
Moumitha,example@gmail.com,23-02-2007,7376242AL222
Thulasika R,another@gmail.com,10-02-2006,7376241CS384
```

---

## 🔒 Security Notes

- Never commit `config.json` to version control (it contains your App Password)
- Add it to `.gitignore`
- For production, use environment variables instead:
  ```
  EMAIL_SENDER=you@gmail.com
  EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  ```
