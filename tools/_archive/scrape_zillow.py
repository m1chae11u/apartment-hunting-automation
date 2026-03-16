"""
scrape_zillow.py — Scrape Zillow rentals via Apify.

Calls the maxcopell/zillow-scraper actor with a pre-built SF rental
search URL, normalizes output to the standard listing schema, and
saves to .tmp/zillow_raw.json.

Usage:
    python tools/scrape_zillow.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ACTOR_ID = os.getenv("APIFY_ZILLOW_ACTOR", "maxcopell/zillow-scraper")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")

# Zillow searchQueryState for SF 1BR rentals $2500-$3500, condo + apartment.
# Map bounds are tight to the Caltrain corridor (~1mi around 4th & King
# and 22nd St stations): SoMa, South Beach, Mission Bay, Dogpatch, Potrero Hill.
# This avoids scraping irrelevant neighborhoods (Nob Hill, Richmond, etc.)
# that process.py would just filter out anyway.
SEARCH_QUERY_STATE = {
    "pagination": {},
    "isMapVisible": True,
    "mapBounds": {
        "west": -122.4150,
        "east": -122.3750,
        "south": 37.7430,
        "north": 37.7900,
    },
    "filterState": {
        "fr": {"value": True},       # for rent
        "fsba": {"value": False},     # exclude for sale by agent
        "fsbo": {"value": False},     # exclude for sale by owner
        "nc": {"value": False},       # exclude new construction
        "cmsn": {"value": False},     # exclude coming soon
        "auc": {"value": False},      # exclude auction
        "fore": {"value": False},     # exclude foreclosure
        "beds": {"min": 1, "max": 1},
        "price": {"min": 2500, "max": 3500},
        "mp": {"min": 2500, "max": 3500},
    },
    "isListVisible": True,
}


def _build_search_url() -> str:
    qs = quote(json.dumps(SEARCH_QUERY_STATE, separators=(",", ":")))
    return f"https://www.zillow.com/san-francisco-ca/rentals/?searchQueryState={qs}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_listing_id(url: str) -> str:
    canonical = url.split("?")[0].lower().rstrip("/")
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def normalize_address(raw: str) -> str:
    if not raw:
        return ""
    cleaned = re.sub(r"\(.*?\)", "", raw)
    cleaned = " ".join(cleaned.split())
    if "san francisco" not in cleaned.lower():
        cleaned = f"{cleaned}, San Francisco, CA"
    return cleaned.strip(", ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(item: dict, *keys, default=None):
    """Try multiple keys, return first non-None value."""
    for key in keys:
        val = item.get(key)
        if val is not None:
            return val
    return default


def _parse_price(val) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    digits = re.sub(r"[^\d]", "", str(val))
    return int(digits) if digits else None


def _parse_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    match = re.search(r"[\d]+\.?[\d]*", str(val))
    return float(match.group()) if match else None


# ---------------------------------------------------------------------------
# Normalize Apify output → standard schema
# ---------------------------------------------------------------------------

def normalize_listing(item: dict) -> dict | None:
    """Convert one Apify Zillow result to our standard schema."""
    now = _now_iso()

    # URL — Zillow detailUrl may be relative
    detail_url = _get(item, "detailUrl", "url", "link")
    if not detail_url:
        return None
    if detail_url.startswith("/"):
        detail_url = f"https://www.zillow.com{detail_url}"

    # Address — Zillow provides both flat and structured
    address_full = _get(item, "address", default="")
    street = _get(item, "addressStreet", "streetAddress", default="")
    city = _get(item, "addressCity", "city", default="")
    state = _get(item, "addressState", "state", default="")
    zipcode = _get(item, "addressZipcode", "zipcode", default="")

    if not address_full and street:
        parts = [street]
        if city:
            parts.append(city)
        if state:
            parts.append(state)
        if zipcode:
            parts.append(zipcode)
        address_full = ", ".join(parts)

    # Also check nested hdpData.homeInfo for richer data
    hdp = item.get("hdpData", {})
    home_info = hdp.get("homeInfo", {}) if isinstance(hdp, dict) else {}

    # Price — prefer unformatted numeric
    price = _parse_price(
        _get(item, "unformattedPrice")
        or _get(home_info, "price")
        or _get(item, "price")
    )

    # Beds/baths/sqft
    beds = _parse_float(_get(item, "beds") or _get(home_info, "bedrooms"))
    baths = _parse_float(_get(item, "baths") or _get(home_info, "bathrooms"))
    area = _parse_float(_get(item, "area") or _get(home_info, "livingArea"))
    sqft = int(area) if area and area > 100 else None

    # Geo
    lat_long = item.get("latLong", {})
    if isinstance(lat_long, dict):
        lat = _parse_float(lat_long.get("latitude") or _get(home_info, "latitude"))
        lon = _parse_float(lat_long.get("longitude") or _get(home_info, "longitude"))
    else:
        lat = _parse_float(_get(home_info, "latitude"))
        lon = _parse_float(_get(home_info, "longitude"))

    # Description (search results usually don't have full description)
    description = _get(home_info, "description", default="")
    status_text = _get(item, "statusText", default="")

    return {
        "listing_id": make_listing_id(detail_url),
        "source": "zillow",
        "title": street or address_full,
        "url": detail_url,
        "price": price,
        "bedrooms": beds if beds else 1.0,
        "bathrooms": baths,
        "sqft": sqft,
        "address_raw": street or address_full,
        "address_normalized": normalize_address(address_full),
        "neighborhood": _get(home_info, "neighborhood", item.get("neighborhood")),
        "lat": lat,
        "lon": lon,
        "description_full": description or status_text,
        "first_seen": now,
        "last_seen": now,
    }


# ---------------------------------------------------------------------------
# Scrape
# ---------------------------------------------------------------------------

def scrape_zillow() -> list[dict]:
    """Run the Apify Zillow actor and return normalized listings."""
    if not APIFY_TOKEN:
        print("[ERROR] APIFY_API_TOKEN not set in .env")
        return []

    client = ApifyClient(token=APIFY_TOKEN)

    search_url = _build_search_url()
    run_input = {
        "searchUrls": [{"url": search_url}],
        "extractionMethod": "PAGINATION",
    }

    print(f"[INFO] Starting Zillow scrape: SF 1BR rentals $2500-$3500")
    print(f"[INFO] Actor: {ACTOR_ID}")

    try:
        run = client.actor(ACTOR_ID).call(run_input=run_input)
    except Exception as exc:
        print(f"[ERROR] Apify actor failed: {exc}")
        return []

    status = run.get("status")
    print(f"[INFO] Actor run finished with status: {status}")

    if status != "SUCCEEDED":
        print(f"[WARN] Actor did not succeed (status={status}), checking for partial results")

    # Fetch results
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        print("[ERROR] No dataset returned from actor run")
        return []

    raw_items = list(client.dataset(dataset_id).iterate_items())
    print(f"[INFO] Got {len(raw_items)} raw items from Apify")

    if raw_items:
        print(f"[DEBUG] Sample item keys: {sorted(raw_items[0].keys())}")

    # Normalize
    listings = []
    for item in raw_items:
        normalized = normalize_listing(item)
        if normalized:
            listings.append(normalized)

    print(f"[INFO] Normalized {len(listings)} listings from Zillow")
    return listings


def save_raw(listings: list[dict], path: str = ".tmp/zillow_raw.json") -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(listings, fh, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved {len(listings)} listings → {path}")


if __name__ == "__main__":
    listings = scrape_zillow()
    save_raw(listings)

    if listings:
        sample = listings[0]
        print(f"\nSample: {sample['title']} — ${sample['price']}")
