from __future__ import annotations

"""
sheets_writer.py

Writes apartment listings and run logs to a Google Sheet.
Part of the WAT framework apartment hunting automation.
"""

import os
import json
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "1XMMKEQ_e3NobZbyi1NW58dM2nCRuiTyGpkDO-OgDlkY")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

LISTINGS_HEADERS = [
    "listing_id",
    "source",
    "title",
    "url",
    "price",
    "bedrooms",
    "bathrooms",
    "sqft",
    "address_raw",
    "address_normalized",
    "neighborhood",
    "lat",
    "lon",
    "dist_4th_king_mi",
    "dist_22nd_st_mi",
    "nearest_caltrain_mi",
    "floor_number",
    "has_inunit_laundry",
    "is_ground_floor",
    "has_view",
    "has_doorman",
    "is_new_construction",
    "has_gym",
    "is_pet_friendly",
    "has_rooftop",
    "has_balcony",
    "description_snippet",
    "score_total",
    "score_urban",
    "score_price",
    "score_caltrain",
    "score_amenities",
    "auto_rejected",
    "reject_reason",
    "first_seen",
    "last_seen",
    "status",
    "notes",
]

RUN_LOG_HEADERS = [
    "timestamp",
    "source",
    "listings_scraped",
    "listings_new",
    "listings_updated",
    "listings_rejected",
    "errors",
    "duration_seconds",
]

# Column index (1-based) of last_seen in LISTINGS_HEADERS
LAST_SEEN_COL = LISTINGS_HEADERS.index("last_seen") + 1  # = 36


# ---------------------------------------------------------------------------
# Authentication & sheet access
# ---------------------------------------------------------------------------

def authenticate() -> gspread.Client:
    """
    Authenticate using a service account JSON file.

    Reads the credentials path from GOOGLE_APPLICATION_CREDENTIALS env var.
    Returns an authenticated gspread Client.
    """
    creds_path = CREDENTIALS_PATH

    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"\n[sheets_writer] credentials.json not found at: {os.path.abspath(creds_path)}\n"
            "To fix this:\n"
            "  1. Go to https://console.cloud.google.com/ and open your project.\n"
            "  2. Navigate to IAM & Admin > Service Accounts.\n"
            "  3. Create or select a service account, then generate a JSON key.\n"
            "  4. Download the key and save it as 'credentials.json' in the project root.\n"
            "  5. Share your Google Sheet with the service account email (Editor access).\n"
            "  6. Set GOOGLE_APPLICATION_CREDENTIALS=credentials.json in your .env file.\n"
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


def get_sheet(client: gspread.Client, sheet_name: str) -> gspread.Worksheet:
    """
    Open the spreadsheet by ID and return the named worksheet.
    Creates the worksheet if it doesn't already exist.
    """
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"[sheets_writer] Worksheet '{sheet_name}' not found — creating it.")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=50)

    return worksheet


# ---------------------------------------------------------------------------
# Header management
# ---------------------------------------------------------------------------

def ensure_headers(worksheet: gspread.Worksheet, headers: list[str]) -> None:
    """
    Write headers to row 1 only if row 1 is currently empty.
    Never overwrites existing header content.
    """
    first_row = worksheet.row_values(1)
    if not any(cell.strip() for cell in first_row):
        worksheet.insert_row(headers, index=1, value_input_option="USER_ENTERED")
        print(f"[sheets_writer] Headers written to '{worksheet.title}'.")
    else:
        print(f"[sheets_writer] Headers already present in '{worksheet.title}' — skipping.")


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_existing_listing_ids(client: gspread.Client) -> set[str]:
    """
    Return the set of all listing_id values already in the Listings sheet.
    Reads column A, skips the header row.
    """
    worksheet = get_sheet(client, "Listings")
    col_a = worksheet.col_values(1)  # includes header
    existing_ids = {val.strip() for val in col_a[1:] if val.strip()}
    return existing_ids


# ---------------------------------------------------------------------------
# Row conversion
# ---------------------------------------------------------------------------

def _clean(value, round_floats: bool = False):
    """Convert a value to a Sheets-safe scalar."""
    if value is None:
        return ""
    if isinstance(value, float):
        if round_floats:
            return round(value, 4)
        return round(value, 4)
    if isinstance(value, bool):
        # Keep booleans as TRUE/FALSE strings so Sheets interprets them correctly
        return str(value).upper()
    return value


def listing_to_row(listing: dict) -> list:
    """
    Convert a listing dict to an ordered list matching LISTINGS_HEADERS.
    None values become empty strings; floats are rounded to 4 decimal places.
    """
    float_fields = {
        "price", "lat", "lon",
        "dist_4th_king_mi", "dist_22nd_st_mi", "nearest_caltrain_mi",
        "score_total", "score_urban", "score_price", "score_caltrain", "score_amenities",
    }

    row = []
    for col in LISTINGS_HEADERS:
        raw = listing.get(col)
        if raw is None:
            row.append("")
        elif isinstance(raw, float) or col in float_fields:
            try:
                row.append(round(float(raw), 4))
            except (TypeError, ValueError):
                row.append(raw if raw is not None else "")
        elif isinstance(raw, bool):
            row.append(str(raw).upper())
        else:
            row.append(raw)

    return row


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def append_listings(client: gspread.Client, listings: list[dict]) -> int:
    """
    Append listings as rows to the Listings sheet in batches.
    Returns the count of successfully appended rows.
    """
    if not listings:
        return 0

    worksheet = get_sheet(client, "Listings")
    ensure_headers(worksheet, LISTINGS_HEADERS)

    rows = [listing_to_row(listing) for listing in listings]
    try:
        worksheet.append_rows(rows, value_input_option="USER_ENTERED")
        print(f"[sheets_writer] Appended {len(rows)}/{len(listings)} listings.")
        return len(rows)
    except gspread.exceptions.APIError as exc:
        print(f"[sheets_writer] ERROR: append_listings failed: {exc}")
        return 0


def update_last_seen(client: gspread.Client, listing_id: str, timestamp: str) -> bool:
    """
    Find the row with matching listing_id in column A and update its last_seen cell.
    Returns True if the row was found and updated, False otherwise.
    """
    worksheet = get_sheet(client, "Listings")

    try:
        cell = worksheet.find(listing_id, in_column=1)
    except gspread.exceptions.CellNotFound:
        print(f"[sheets_writer] listing_id '{listing_id}' not found — skipping last_seen update.")
        return False

    try:
        worksheet.update_cell(cell.row, LAST_SEEN_COL, timestamp)
        return True
    except gspread.exceptions.APIError as exc:
        print(f"[sheets_writer] WARNING: Could not update last_seen for '{listing_id}': {exc}")
        return False


def log_run(client: gspread.Client, run_metadata: dict) -> None:
    """
    Append one row to the Run Log sheet.
    Automatically prepends the current UTC timestamp.

    Expected run_metadata keys:
        source, listings_scraped, listings_new, listings_updated,
        listings_rejected, errors, duration_seconds
    """
    worksheet = get_sheet(client, "Run Log")
    ensure_headers(worksheet, RUN_LOG_HEADERS)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    errors_val = run_metadata.get("errors", "")
    if isinstance(errors_val, list):
        errors_val = "; ".join(str(e) for e in errors_val)

    row = [
        timestamp,
        run_metadata.get("source", ""),
        run_metadata.get("listings_scraped", 0),
        run_metadata.get("listings_new", 0),
        run_metadata.get("listings_updated", 0),
        run_metadata.get("listings_rejected", 0),
        errors_val,
        run_metadata.get("duration_seconds", ""),
    ]

    try:
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        print(f"[sheets_writer] Run logged at {timestamp}.")
    except gspread.exceptions.APIError as exc:
        print(f"[sheets_writer] WARNING: Failed to log run: {exc}")


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def write_results(
    new_listings: list[dict],
    updated_listing_ids: list[str],
    run_metadata: dict,
) -> dict:
    """
    Top-level function to write a pipeline run's results to Google Sheets.

    Steps:
      1. Authenticate with service account credentials.
      2. Append new listings to the Listings sheet.
      3. Update last_seen for listings that already exist.
      4. Log the run to the Run Log sheet.

    Returns:
        {
            "appended": int,   # rows successfully appended
            "updated": int,    # last_seen timestamps successfully updated
            "errors": list[str]
        }
    """
    errors: list[str] = []

    # 1. Authenticate
    try:
        client = authenticate()
    except FileNotFoundError as exc:
        print(exc)
        raise

    # 2. Append new listings
    appended = 0
    try:
        appended = append_listings(client, new_listings)
    except Exception as exc:
        msg = f"append_listings failed: {exc}"
        print(f"[sheets_writer] ERROR: {msg}")
        errors.append(msg)

    # 3. Update last_seen for existing listings
    updated = 0
    timestamp_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for listing_id in updated_listing_ids:
        try:
            success = update_last_seen(client, listing_id, timestamp_now)
            if success:
                updated += 1
        except Exception as exc:
            msg = f"update_last_seen failed for '{listing_id}': {exc}"
            print(f"[sheets_writer] ERROR: {msg}")
            errors.append(msg)

    # 4. Log the run
    try:
        log_run(client, run_metadata)
    except Exception as exc:
        msg = f"log_run failed: {exc}"
        print(f"[sheets_writer] ERROR: {msg}")
        errors.append(msg)

    result = {"appended": appended, "updated": updated, "errors": errors}
    print(f"[sheets_writer] Done. appended={appended}, updated={updated}, errors={len(errors)}")
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Sheets writer loaded. Run write_results() to write listings.")
    print("\nListings column headers:")
    for i, header in enumerate(LISTINGS_HEADERS, start=1):
        print(f"  {i:>2}. {header}")
    print("\nRun Log column headers:")
    for i, header in enumerate(RUN_LOG_HEADERS, start=1):
        print(f"  {i:>2}. {header}")
