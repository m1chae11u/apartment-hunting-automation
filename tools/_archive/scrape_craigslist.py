from __future__ import annotations

"""
scrape_craigslist.py

Scrapes SF Craigslist housing listings and returns canonical listing dicts
matching the shared schema used across the apartment-hunting WAT framework.

Usage (test mode):
    python tools/scrape_craigslist.py
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = (
    "https://sfbay.craigslist.org/search/sfc/apa"
    "?min_price=2500&max_price=3500"
    "&min_bedrooms=1&max_bedrooms=1"
    "&availabilityMode=0&sort=date"
)

MAX_LISTINGS_PER_SOURCE = int(os.getenv("MAX_LISTINGS_PER_SOURCE", 360))
PAGE_SIZE = 120  # Craigslist default results per page

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+ml;q=0.9,*/*;q=0.8",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_listing_id(url: str) -> str:
    """Return MD5 hex digest of the canonical URL (no query params, lowercase)."""
    canonical = url.split("?")[0].lower().rstrip("/")
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def normalize_address(raw: str) -> str:
    """
    Clean a raw address string for geocoding:
    - Strip extra whitespace
    - Remove parenthetical neighborhood names
    - Append 'San Francisco, CA' if not already present
    """
    if not raw:
        return ""
    # Remove content in parentheses (e.g., "(Mission District)")
    cleaned = re.sub(r"\(.*?\)", "", raw)
    # Collapse whitespace
    cleaned = " ".join(cleaned.split())
    # Append city/state if missing
    if "san francisco" not in cleaned.lower():
        cleaned = f"{cleaned}, San Francisco, CA"
    return cleaned.strip(", ")


def _now_iso() -> str:
    """Return current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _empty_listing() -> dict:
    """Return a listing dict pre-populated with all schema keys at their defaults."""
    now = _now_iso()
    return {
        "listing_id": None,
        "source": "craigslist",
        "title": None,
        "url": None,
        "price": None,
        "bedrooms": 1.0,
        "bathrooms": None,
        "sqft": None,
        "address_raw": "",
        "address_normalized": "",
        "neighborhood": None,
        "lat": None,
        "lon": None,
        "dist_4th_king_mi": None,
        "dist_22nd_st_mi": None,
        "nearest_caltrain_mi": None,
        "floor_number": None,
        "has_inunit_laundry": None,
        "is_ground_floor": False,
        "has_view": False,
        "has_doorman": False,
        "is_new_construction": False,
        "has_gym": False,
        "is_pet_friendly": False,
        "has_rooftop": False,
        "has_balcony": False,
        "description_snippet": "",
        "description_full": "",
        "score_total": None,
        "score_urban": None,
        "score_price": None,
        "score_caltrain": None,
        "score_amenities": None,
        "auto_rejected": False,
        "reject_reason": None,
        "first_seen": now,
        "last_seen": now,
        "status": "new",
    }


def _parse_price(text: str) -> int | None:
    """Extract integer dollar amount from a string like '$2,950'."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_float(text: str) -> float | None:
    """Extract the first decimal number from a string."""
    match = re.search(r"[\d]+\.?[\d]*", text or "")
    return float(match.group()) if match else None


def _parse_int(text: str) -> int | None:
    """Extract first integer from a string."""
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else None


# ---------------------------------------------------------------------------
# Core scraping functions
# ---------------------------------------------------------------------------


def scrape_search_page(start: int = 0) -> list[dict]:
    """
    Fetch one page of Craigslist search results and parse the embedded JSON-LD
    to return a list of partial listing dicts (url, title, lat, lon, price,
    bedrooms).

    Returns an empty list on any failure.
    """
    url = f"{BASE_URL}&start={start}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARNING] Failed to fetch search page (start={start}): {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # Craigslist embeds structured data in a <script> with id="ld_searchpage_results"
    ld_tag = soup.find("script", {"id": "ld_searchpage_results", "type": "application/ld+json"})
    if not ld_tag:
        print(f"[WARNING] JSON-LD tag not found on search page (start={start}). "
              "Craigslist may have changed its markup.")
        return []

    try:
        ld_data = json.loads(ld_tag.string)
    except json.JSONDecodeError as exc:
        print(f"[WARNING] Failed to parse JSON-LD on search page (start={start}): {exc}")
        return []

    # The top-level object is typically an ItemList; items live in "itemListElement"
    items = []
    if isinstance(ld_data, dict):
        items = ld_data.get("itemListElement", [])
    elif isinstance(ld_data, list):
        items = ld_data

    # Extract listing URLs from HTML links (JSON-LD items may lack URLs)
    html_links = [a["href"] for a in soup.select('a[href*="/apa/"]') if a.get("href")]

    partial_listings = []
    for idx, item in enumerate(items):
        # Each item may itself be a wrapper with "item" sub-key
        listing_data = item.get("item", item) if isinstance(item, dict) else {}
        if not listing_data:
            continue

        # Try URL from JSON-LD first, fall back to positional HTML link
        listing_url = listing_data.get("url") or listing_data.get("@id")
        if not listing_url and idx < len(html_links):
            listing_url = html_links[idx]
        if not listing_url:
            continue

        partial = _empty_listing()
        partial["url"] = listing_url
        partial["listing_id"] = make_listing_id(listing_url)
        partial["title"] = listing_data.get("name")

        # Price may appear as "offers" sub-object or top-level
        offers = listing_data.get("offers", {})
        if isinstance(offers, dict):
            price_raw = offers.get("price") or offers.get("lowPrice")
            if price_raw is not None:
                try:
                    partial["price"] = int(float(str(price_raw)))
                except (ValueError, TypeError):
                    pass

        # Geo coordinates — may be in a "geo" sub-object or top-level
        geo = listing_data.get("geo", {})
        if isinstance(geo, dict):
            lat = geo.get("latitude")
            lon = geo.get("longitude")
        else:
            lat = None
            lon = None
        # Fall back to top-level latitude/longitude (current CL format)
        if lat is None:
            lat = listing_data.get("latitude")
        if lon is None:
            lon = listing_data.get("longitude")
        if lat is not None:
            try:
                partial["lat"] = float(lat)
            except (ValueError, TypeError):
                pass
        if lon is not None:
            try:
                partial["lon"] = float(lon)
            except (ValueError, TypeError):
                pass

        partial_listings.append(partial)

    return partial_listings


def scrape_listing_detail(url: str) -> dict:
    """
    Fetch a single Craigslist listing page and extract detailed fields:
    description_full, address_raw, neighborhood, price (fallback), bathrooms, sqft.

    Returns a dict of fields to merge into the partial listing. Returns an
    empty dict on unrecoverable errors so the caller can decide whether to skip.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            print(f"[WARNING] 404 on listing detail: {url}")
            return {}
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARNING] Connection error fetching listing detail ({url}): {exc}")
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    detail: dict = {}

    # ------------------------------------------------------------------ #
    # Description
    # ------------------------------------------------------------------ #
    body_tag = soup.select_one("#postingbody") or soup.select_one(".userbody")
    if body_tag:
        # Craigslist inserts a "QR code" notice block — remove it
        for junk in body_tag.select(".print-information, .postinginfos"):
            junk.decompose()
        full_text = body_tag.get_text(separator="\n").strip()
        detail["description_full"] = full_text
        detail["description_snippet"] = full_text[:300]
    else:
        detail["description_full"] = ""
        detail["description_snippet"] = ""

    # ------------------------------------------------------------------ #
    # Price (fallback if not captured from JSON-LD)
    # ------------------------------------------------------------------ #
    price_tag = soup.select_one(".price")
    if price_tag:
        detail["price"] = _parse_price(price_tag.get_text())

    # ------------------------------------------------------------------ #
    # Address
    # ------------------------------------------------------------------ #
    # Try .mapaddress first, then [data-address] attribute
    addr_tag = soup.select_one(".mapaddress")
    if addr_tag:
        raw_addr = addr_tag.get_text(separator=" ").strip()
    else:
        map_div = soup.select_one("[data-address]")
        raw_addr = map_div["data-address"].strip() if map_div else ""

    detail["address_raw"] = raw_addr
    detail["address_normalized"] = normalize_address(raw_addr)

    # ------------------------------------------------------------------ #
    # Neighborhood — from breadcrumb or URL path
    # ------------------------------------------------------------------ #
    breadcrumb = soup.select_one(".breadcrumb")
    if breadcrumb:
        crumbs = [a.get_text(strip=True) for a in breadcrumb.select("a")]
        # Last crumb is usually the neighborhood
        if crumbs:
            detail["neighborhood"] = crumbs[-1]
    else:
        # Fall back to the area slug in the URL path, e.g. /nby/apa/...
        match = re.search(r"sfbay\.craigslist\.org/([^/]+)/apa", url)
        if match:
            detail["neighborhood"] = match.group(1)

    # ------------------------------------------------------------------ #
    # Bathrooms and square footage from attribute groups
    # ------------------------------------------------------------------ #
    # Craigslist renders housing attributes in .attrgroup > span elements
    for span in soup.select(".attrgroup span"):
        text = span.get_text(strip=True).lower()
        if "br" in text and "ba" in text:
            # e.g. "1BR / 1Ba"
            br_match = re.search(r"([\d.]+)\s*br", text)
            ba_match = re.search(r"([\d.]+)\s*ba", text)
            if br_match:
                try:
                    detail["bedrooms"] = float(br_match.group(1))
                except ValueError:
                    pass
            if ba_match:
                try:
                    detail["bathrooms"] = float(ba_match.group(1))
                except ValueError:
                    pass
        elif "ba" in text or "bath" in text:
            val = _parse_float(text)
            if val is not None:
                detail["bathrooms"] = val
        elif "ft" in text or "sq" in text:
            val = _parse_int(text)
            if val and val > 100:  # sanity check
                detail["sqft"] = val

    # Also look for sqft in the housing attribute block directly
    if "sqft" not in detail:
        sqft_tag = soup.find(string=re.compile(r"ft²|sq\s*ft", re.I))
        if sqft_tag:
            val = _parse_int(str(sqft_tag))
            if val and val > 100:
                detail["sqft"] = val

    return detail


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def scrape_craigslist(max_listings: int = MAX_LISTINGS_PER_SOURCE) -> list[dict]:
    """
    Scrape SF Craigslist apartment listings, fetching up to max_listings
    across up to 3 paginated search result pages. For each listing found,
    fetches the detail page to fill in the full schema.

    Returns a list of fully populated listing dicts.
    """
    all_listings: list[dict] = []
    seen_ids: set[str] = set()
    pages_to_fetch = min(3, -(-max_listings // PAGE_SIZE))  # ceiling division

    for page_num in range(pages_to_fetch):
        if len(all_listings) >= max_listings:
            break

        start = page_num * PAGE_SIZE
        print(f"[INFO] Fetching search page {page_num + 1} (start={start}) …")
        partials = scrape_search_page(start=start)

        if not partials:
            print(f"[INFO] No results on page {page_num + 1}. Stopping pagination.")
            break

        time.sleep(1)

        for partial in partials:
            if len(all_listings) >= max_listings:
                break

            listing_id = partial.get("listing_id")
            if not listing_id or listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            listing_url = partial.get("url", "")
            print(f"[INFO] Fetching detail: {listing_url}")

            try:
                detail = scrape_listing_detail(listing_url)
            except Exception as exc:
                print(f"[WARNING] Unexpected error fetching detail for {listing_url}: {exc}")
                detail = {}

            if not detail and not partial.get("title"):
                # Skip listings where we got nothing useful
                print(f"[WARNING] Skipping listing with no usable data: {listing_url}")
                continue

            # Merge detail fields into partial, but don't overwrite values
            # that were already captured from JSON-LD (e.g. lat/lon, price)
            for key, value in detail.items():
                if key in partial and partial[key] is not None and partial[key] != "":
                    continue  # keep the JSON-LD value
                partial[key] = value

            # Ensure required fields have sensible defaults
            if not partial.get("title"):
                partial["title"] = "(no title)"
            if not partial.get("address_normalized") and partial.get("address_raw"):
                partial["address_normalized"] = normalize_address(partial["address_raw"])

            all_listings.append(partial)
            time.sleep(1)

    print(f"[INFO] Scraped {len(all_listings)} listings total.")
    return all_listings


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_raw(listings: list[dict], path: str = ".tmp/craigslist_raw.json") -> None:
    """Save listings to a JSON file, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(listings, fh, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved {len(listings)} listings → {path}")


# ---------------------------------------------------------------------------
# Entry point (test mode)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[INFO] Running in test mode (max_listings=5) …")
    listings = scrape_craigslist(max_listings=5)

    if listings:
        first = listings[0]
        print(f"\nFirst listing:")
        print(f"  Title : {first['title']}")
        print(f"  URL   : {first['url']}")
        print(f"  Price : {first['price']}")
        print(f"  Addr  : {first['address_raw']}")
    else:
        print("[WARNING] No listings returned.")

    save_raw(listings, ".tmp/craigslist_raw.json")
