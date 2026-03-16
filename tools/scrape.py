"""
scrape.py — Scrape Craigslist apartments near Caltrain stations.

Runs geo-bounded searches for each bedroom/price tier around each station,
merges results, dedupes by listing ID, and saves to .tmp/craigslist_raw.json.

Usage:
    python tools/scrape.py              # default: up to 120 listings per tier
    python tools/scrape.py --max 50     # limit total listings per tier
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config — imported from central config.py
# ---------------------------------------------------------------------------

from config import SEARCHES, CALTRAIN_STATIONS, SEARCH_DISTANCE_MI

BASE_URL = "https://sfbay.craigslist.org/search/sfc/apa"


def _build_params(search_tier: dict) -> str:
    """Build CL query params for a given bedroom/price tier."""
    br = search_tier["bedrooms"]
    return (
        f"?min_price={search_tier['min_price']}&max_price={search_tier['max_price']}"
        f"&min_bedrooms={br}&max_bedrooms={br}"
        f"&availabilityMode=0&sort=date"
    )

PAGE_SIZE = 120
DEFAULT_MAX_LISTINGS = 120

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,*/*;q=0.8",
}


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


def _parse_price(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_float(text: str) -> float | None:
    match = re.search(r"[\d]+\.?[\d]*", text or "")
    return float(match.group()) if match else None


def _parse_int(text: str) -> int | None:
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else None


def _empty_listing() -> dict:
    now = _now_iso()
    return {
        "listing_id": None,
        "source": "craigslist",
        "title": None,
        "url": None,
        "price": None,
        "bedrooms": None,
        "bathrooms": None,
        "sqft": None,
        "address_raw": "",
        "address_normalized": "",
        "neighborhood": None,
        "lat": None,
        "lon": None,
        "description_full": "",
        "first_seen": now,
        "last_seen": now,
    }


# ---------------------------------------------------------------------------
# Core scraping
# ---------------------------------------------------------------------------

def scrape_search_page(center: dict, search_tier: dict, start: int = 0) -> list[dict]:
    """Fetch one page of geo-bounded CL search results for a bedroom/price tier."""
    params = _build_params(search_tier)
    url = (
        f"{BASE_URL}{params}"
        f"&lat={center['lat']}&lon={center['lon']}"
        f"&search_distance={SEARCH_DISTANCE_MI}"
        f"&start={start}"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] Failed to fetch search page ({center['name']}, start={start}): {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    ld_tag = soup.find("script", {"id": "ld_searchpage_results", "type": "application/ld+json"})
    if not ld_tag:
        print(f"[WARN] No JSON-LD on search page ({center['name']}, start={start})")
        return []

    try:
        ld_data = json.loads(ld_tag.string)
    except json.JSONDecodeError as exc:
        print(f"[WARN] Bad JSON-LD ({center['name']}, start={start}): {exc}")
        return []

    items = []
    if isinstance(ld_data, dict):
        items = ld_data.get("itemListElement", [])
    elif isinstance(ld_data, list):
        items = ld_data

    html_links = [a["href"] for a in soup.select('a[href*="/apa/"]') if a.get("href")]

    partials = []
    for idx, item in enumerate(items):
        listing_data = item.get("item", item) if isinstance(item, dict) else {}
        if not listing_data:
            continue

        listing_url = listing_data.get("url") or listing_data.get("@id")
        if not listing_url and idx < len(html_links):
            listing_url = html_links[idx]
        if not listing_url:
            continue

        partial = _empty_listing()
        partial["url"] = listing_url
        partial["listing_id"] = make_listing_id(listing_url)
        partial["title"] = listing_data.get("name")

        # Price
        offers = listing_data.get("offers", {})
        if isinstance(offers, dict):
            price_raw = offers.get("price") or offers.get("lowPrice")
            if price_raw is not None:
                try:
                    partial["price"] = int(float(str(price_raw)))
                except (ValueError, TypeError):
                    pass

        # Geo
        geo = listing_data.get("geo", {})
        if isinstance(geo, dict):
            lat = geo.get("latitude")
            lon = geo.get("longitude")
        else:
            lat = None
            lon = None
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

        partials.append(partial)

    return partials


def scrape_listing_detail(url: str) -> dict:
    """Fetch a single CL listing page for description, address, etc."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
    except requests.RequestException:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    detail = {}

    # Description
    body_tag = soup.select_one("#postingbody") or soup.select_one(".userbody")
    if body_tag:
        for junk in body_tag.select(".print-information, .postinginfos"):
            junk.decompose()
        detail["description_full"] = body_tag.get_text(separator="\n").strip()
    else:
        detail["description_full"] = ""

    # Address
    addr_tag = soup.select_one(".mapaddress")
    if addr_tag:
        raw_addr = addr_tag.get_text(separator=" ").strip()
    else:
        map_div = soup.select_one("[data-address]")
        raw_addr = map_div["data-address"].strip() if map_div else ""
    detail["address_raw"] = raw_addr
    detail["address_normalized"] = normalize_address(raw_addr)

    # Neighborhood
    breadcrumb = soup.select_one(".breadcrumb")
    if breadcrumb:
        crumbs = [a.get_text(strip=True) for a in breadcrumb.select("a")]
        if crumbs:
            detail["neighborhood"] = crumbs[-1]

    # Bedrooms / Bathrooms / sqft
    for span in soup.select(".attrgroup span"):
        text = span.get_text(strip=True).lower()
        if "br" in text and "ba" in text:
            br_match = re.search(r"([\d.]+)\s*br", text)
            if br_match:
                try:
                    detail["bedrooms"] = int(float(br_match.group(1)))
                except ValueError:
                    pass
            ba_match = re.search(r"([\d.]+)\s*ba", text)
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
            if val and val > 100:
                detail["sqft"] = val

    if "sqft" not in detail:
        sqft_tag = soup.find(string=re.compile(r"ft²|sq\s*ft", re.I))
        if sqft_tag:
            val = _parse_int(str(sqft_tag))
            if val and val > 100:
                detail["sqft"] = val

    # Price fallback
    price_tag = soup.select_one(".price")
    if price_tag:
        detail["price"] = _parse_price(price_tag.get_text())

    return detail


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def scrape_craigslist(max_listings: int = DEFAULT_MAX_LISTINGS) -> list[dict]:
    """
    Search around each Caltrain station for each bedroom/price tier,
    fetch details, merge and dedupe.
    """
    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    for tier in SEARCHES:
        br = tier["bedrooms"]
        print(f"\n{'='*60}")
        print(f"[INFO] Searching {br}BR (${tier['min_price']}-${tier['max_price']})")
        print(f"{'='*60}")

        for center in CALTRAIN_STATIONS:
            print(f"\n[INFO] Searching 1mi around {center['name']} ({center['lat']}, {center['lon']})")

            partials = scrape_search_page(center, tier, start=0)
            print(f"[INFO] Found {len(partials)} results near {center['name']}")

            if not partials:
                continue

            time.sleep(1)

            for partial in partials:
                lid = partial.get("listing_id")
                if not lid or lid in seen_ids:
                    continue
                seen_ids.add(lid)

                listing_url = partial.get("url", "")
                print(f"[INFO] Detail: {listing_url}")

                try:
                    detail = scrape_listing_detail(listing_url)
                except Exception as exc:
                    print(f"[WARN] Error on detail {listing_url}: {exc}")
                    detail = {}

                if not detail and not partial.get("title"):
                    continue

                # Merge — keep JSON-LD values over detail page values
                for key, value in detail.items():
                    if key in partial and partial[key] is not None and partial[key] != "":
                        continue
                    partial[key] = value

                # Fall back to search tier bedroom count if not parsed from detail
                if partial.get("bedrooms") is None:
                    partial["bedrooms"] = br

                if not partial.get("title"):
                    partial["title"] = "(no title)"
                if not partial.get("address_normalized") and partial.get("address_raw"):
                    partial["address_normalized"] = normalize_address(partial["address_raw"])

                all_listings.append(partial)
                time.sleep(1)

    print(f"\n[INFO] Total: {len(all_listings)} unique listings across {len(SEARCHES)} tiers x {len(CALTRAIN_STATIONS)} stations")
    return all_listings


def save_raw(listings: list[dict], path: str = ".tmp/craigslist_raw.json") -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(listings, fh, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved {len(listings)} listings → {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape CL apartments near Caltrain")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_LISTINGS, help="Max listings")
    args = parser.parse_args()

    listings = scrape_craigslist(max_listings=args.max)
    save_raw(listings)

    if listings:
        print(f"\nSample: {listings[0]['title']} — ${listings[0]['price']}")
