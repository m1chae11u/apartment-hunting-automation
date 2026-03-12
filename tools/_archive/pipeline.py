from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from deduplicate import run_deduplication
from email_digest import send_digest
from geocode import enrich_with_caltrain
from score import extract_features, process_listings
from scrape_craigslist import save_raw, scrape_craigslist
from sheets_writer import authenticate, get_existing_listing_ids, write_results

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TMP_DIR = Path(__file__).parent.parent / ".tmp"
LAST_RUN_PATH = TMP_DIR / "last_run.json"
RAW_CRAIGSLIST_PATH = TMP_DIR / "craigslist_raw.json"
SCORED_OUTPUT_PATH = TMP_DIR / "scored_listings.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_pipeline(sources: list[str] = ["craigslist"]) -> dict:
    start_time = time.time()
    timestamp = _now_iso()
    errors: list[str] = []

    listings_scraped = 0
    listings_new = 0
    listings_updated = 0
    listings_rejected = 0
    email_sent = False

    all_listings: list[dict] = []
    scored_listings: list[dict] = []
    new_listings: list[dict] = []
    updated_ids: list[str] = []

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    max_listings = int(os.getenv("MAX_LISTINGS_PER_SOURCE", "360"))

    # Step 1: Scrape
    log.info("Step 1/8 — Scraping sources: %s", sources)
    try:
        if "craigslist" in sources:
            raw_listings = scrape_craigslist(max_listings)
            save_raw(raw_listings, str(RAW_CRAIGSLIST_PATH))
            all_listings.extend(raw_listings)
            listings_scraped = len(all_listings)
            log.info("Scraped %d listings from Craigslist", len(raw_listings))
        else:
            log.warning("No recognized sources in: %s", sources)
    except Exception as exc:
        msg = f"Scrape step failed: {exc}"
        log.error(msg)
        errors.append(msg)
        result = {
            "status": "error",
            "sources": sources,
            "listings_scraped": listings_scraped,
            "listings_new": listings_new,
            "listings_updated": listings_updated,
            "listings_rejected": listings_rejected,
            "email_sent": email_sent,
            "errors": errors,
            "duration_seconds": round(time.time() - start_time, 2),
            "timestamp": timestamp,
        }
        save_last_run_result(result)
        return result

    # Step 2: Geocode
    log.info("Step 2/8 — Geocoding %d listings", len(all_listings))
    geocoded: list[dict] = []
    for listing in all_listings:
        try:
            enriched = enrich_with_caltrain(listing)
            geocoded.append(enriched)
        except Exception as exc:
            msg = f"Geocode failed for listing {listing.get('id', '?')}: {exc}"
            log.warning(msg)
            errors.append(msg)
            geocoded.append(listing)
    log.info("Geocoded %d listings (%d errors)", len(geocoded), sum(1 for e in errors if "Geocode" in e))

    # Step 3: Extract features
    log.info("Step 3/8 — Extracting features from %d listings", len(geocoded))
    featured: list[dict] = []
    for listing in geocoded:
        try:
            enriched = extract_features(listing)
            featured.append(enriched)
        except Exception as exc:
            msg = f"Feature extraction failed for listing {listing.get('id', '?')}: {exc}"
            log.warning(msg)
            errors.append(msg)
            featured.append(listing)
    log.info("Feature extraction complete")

    # Step 4: Score
    log.info("Step 4/8 — Scoring and filtering %d listings", len(featured))
    try:
        scored_listings = process_listings(featured)
        listings_rejected = len(featured) - len(scored_listings)
        log.info(
            "Scoring complete — %d passed, %d rejected",
            len(scored_listings),
            listings_rejected,
        )
    except Exception as exc:
        msg = f"Scoring step failed: {exc}"
        log.error(msg)
        errors.append(msg)
        scored_listings = featured

    # Step 5: Deduplicate
    log.info("Step 5/8 — Deduplicating against existing Sheets data")
    dedup_result: dict = {}
    existing_ids: set = set()
    sheets_client = None
    try:
        sheets_client = authenticate()
        existing_ids = get_existing_listing_ids(sheets_client)
        log.info("Fetched %d existing IDs from Sheets", len(existing_ids))
        dedup_result = run_deduplication(scored_listings, existing_ids)
        new_listings = dedup_result.get("new_listings", [])
        updated_ids = dedup_result.get("updated_ids", [])
        listings_new = len(new_listings)
        listings_updated = len(updated_ids)
        log.info(
            "Deduplication complete — %d new, %d updated",
            listings_new,
            listings_updated,
        )
    except Exception as exc:
        msg = f"Deduplication step failed: {exc}"
        log.error(msg)
        errors.append(msg)
        new_listings = scored_listings
        listings_new = len(new_listings)

    # Step 6: Write to Sheets
    log.info("Step 6/8 — Writing %d new listings to Sheets", listings_new)
    run_metadata = {
        "timestamp": timestamp,
        "sources": sources,
        "listings_scraped": listings_scraped,
        "listings_new": listings_new,
        "listings_updated": listings_updated,
        "listings_rejected": listings_rejected,
    }
    try:
        write_results(new_listings, updated_ids, run_metadata)
        log.info("Sheets write complete")
    except Exception as exc:
        msg = f"Sheets write step failed: {exc}"
        log.error(msg)
        errors.append(msg)

    # Step 7: Send email digest
    log.info("Step 7/8 — Sending email digest")
    try:
        email_sent = send_digest(new_listings, run_metadata)
        log.info("Email digest sent: %s", email_sent)
    except Exception as exc:
        msg = f"Email digest step failed: {exc}"
        log.error(msg)
        errors.append(msg)

    # Step 8: Save scored output
    log.info("Step 8/8 — Saving scored output to %s", SCORED_OUTPUT_PATH)
    try:
        all_scored = scored_listings
        with open(SCORED_OUTPUT_PATH, "w") as f:
            json.dump(all_scored, f, indent=2)
        log.info("Saved %d scored listings", len(all_scored))
    except Exception as exc:
        msg = f"Saving scored output failed: {exc}"
        log.error(msg)
        errors.append(msg)

    duration = round(time.time() - start_time, 2)

    if not errors:
        status = "success"
    elif scored_listings:
        status = "partial"
    else:
        status = "error"

    result = {
        "status": status,
        "sources": sources,
        "listings_scraped": listings_scraped,
        "listings_new": listings_new,
        "listings_updated": listings_updated,
        "listings_rejected": listings_rejected,
        "email_sent": email_sent,
        "errors": errors,
        "duration_seconds": duration,
        "timestamp": timestamp,
    }

    log.info(
        "Pipeline complete — status=%s, duration=%.2fs, new=%d, updated=%d, errors=%d",
        status,
        duration,
        listings_new,
        listings_updated,
        len(errors),
    )

    save_last_run_result(result)
    return result


def get_last_run_result() -> dict | None:
    if not LAST_RUN_PATH.exists():
        return None
    try:
        with open(LAST_RUN_PATH) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not read last run result: %s", exc)
        return None


def save_last_run_result(result: dict) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(LAST_RUN_PATH, "w") as f:
            json.dump(result, f, indent=2)
    except Exception as exc:
        log.warning("Could not save last run result: %s", exc)


app = FastAPI(title="SF Apartment Hunt Pipeline", version="1.0.0")


@app.post("/run")
async def run_endpoint():
    result = run_pipeline()
    return result


@app.get("/health")
async def health_endpoint():
    return {"status": "ok", "timestamp": _now_iso()}


@app.get("/last-run")
async def last_run_endpoint():
    result = get_last_run_result()
    if result is None:
        return {"status": "no_runs_yet"}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SF Apartment Hunt Pipeline")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--run-once", action="store_true", help="Run pipeline once and exit")
    parser.add_argument("--port", type=int, default=None, help="Port override")
    args = parser.parse_args()

    if args.serve:
        port = args.port or int(os.getenv("PIPELINE_PORT", "8765"))
        print(f"Starting pipeline server on http://localhost:{port}")
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    elif args.run_once:
        result = run_pipeline()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] != "error" else 1)
    else:
        parser.print_help()
