"""
update_sheet.py — Step 4: Write grouped buildings to Google Sheets.

Reads grouped buildings from .tmp/grouped_buildings.json, appends each
to the correct neighborhood tab matching the existing format:
  Row 4 headers: NAME | WEBSITE | RENT/MO | NOTES | GOOGLE ⭐️ RATING | Street View
  Data starts at row 5+

Creates new neighborhood tabs if needed. Skips buildings already present.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Headers matching existing sheet format (row 4)
HEADERS = [
    "NAME",
    "WEBSITE",
    "RENT/MO",
    "DATE ADDED",
    "NOTES",
    "GOOGLE ⭐️ RATING (MAPS)",
    "Street View Vicinity Review/Concensus",
]

HEADER_ROW = 4
DATA_START_ROW = 5


def authenticate() -> gspread.Client:
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


def get_existing_names(worksheet: gspread.Worksheet) -> set[str]:
    """Get all building names already in column A (below header row)."""
    col_a = worksheet.col_values(1)
    # Names start at DATA_START_ROW (index 4 in 0-based)
    names = {name.strip().lower() for name in col_a[HEADER_ROW:] if name.strip()}
    return names


def ensure_tab(spreadsheet: gspread.Spreadsheet, tab_name: str) -> gspread.Worksheet:
    """Get or create a neighborhood tab with the correct headers."""
    try:
        ws = spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"  Creating new tab: {tab_name}")
        ws = spreadsheet.add_worksheet(title=tab_name, rows=200, cols=len(HEADERS))
        # Write headers at row 4
        end_col = chr(ord("A") + len(HEADERS) - 1)
        ws.update(values=[HEADERS], range_name=f"A{HEADER_ROW}:{end_col}{HEADER_ROW}")
        # Bold the header row
        ws.format(f"A{HEADER_ROW}:{end_col}{HEADER_ROW}", {"textFormat": {"bold": True}})
    return ws


def building_to_row(building: dict) -> list:
    """Convert a grouped building to a row matching the sheet format."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [
        building["name"],
        building.get("url", ""),
        building.get("price", ""),
        today,
        "",  # NOTES — user fills this
        "",  # GOOGLE RATING — user fills this
        "",  # Street View — user fills this
    ]


def main():
    input_path = Path(__file__).parent.parent / ".tmp" / "grouped_buildings.json"
    with open(input_path) as f:
        buildings = json.load(f)

    print(f"Loaded {len(buildings)} buildings")

    client = authenticate()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    # Group by neighborhood
    by_neighborhood: dict[str, list[dict]] = {}
    for b in buildings:
        hood = b["neighborhood"]
        by_neighborhood.setdefault(hood, []).append(b)

    total_added = 0
    total_skipped = 0

    for hood, hood_buildings in by_neighborhood.items():
        print(f"\n--- {hood} ---")
        ws = ensure_tab(spreadsheet, hood)
        existing = get_existing_names(ws)

        rows_to_add = []
        for b in hood_buildings:
            if b["name"].strip().lower() in existing:
                print(f"  SKIP (already exists): {b['name']}")
                total_skipped += 1
            else:
                rows_to_add.append(building_to_row(b))
                print(f"  ADD: {b['name']} — {b['price']}")
                total_added += 1

        if rows_to_add:
            # Find next empty row after existing data
            all_values = ws.col_values(1)
            next_row = max(len(all_values) + 1, DATA_START_ROW)
            end_col = chr(ord("A") + len(HEADERS) - 1)
            cell_range = f"A{next_row}:{end_col}{next_row + len(rows_to_add) - 1}"
            ws.update(values=rows_to_add, range_name=cell_range)

    print(f"\n=== DONE ===")
    print(f"Added: {total_added}")
    print(f"Skipped (duplicates): {total_skipped}")


if __name__ == "__main__":
    main()
