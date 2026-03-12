"""
notify.py — Step 5: Send simple email notification when new buildings are found.

Reads .tmp/grouped_buildings.json and sends a short email with the count
and a link to the Google Sheet.
"""

import json
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


def send_notification(added: int, buildings: list[dict]):
    if added == 0:
        print("No new buildings — skipping email.")
        return

    # Build simple text body
    lines = [f"{added} new building(s) found:\n"]
    for b in buildings:
        lines.append(f"  - {b['name']} ({b['neighborhood']}) — {b['price']}")
    lines.append(f"\nView sheet: {SHEET_URL}")

    body = "\n".join(lines)
    subject = f"Apartment Hunt: {added} new building(s) found"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, GMAIL_APP_PASSWORD)
        server.send_message(msg)

    print(f"Email sent to {EMAIL_TO}: {subject}")


def main():
    path = Path(__file__).parent.parent / ".tmp" / "grouped_buildings.json"
    with open(path) as f:
        buildings = json.load(f)

    # For standalone runs, assume all are new
    send_notification(len(buildings), buildings)


if __name__ == "__main__":
    main()
