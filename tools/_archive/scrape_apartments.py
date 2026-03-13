"""
scrape_apartments.py — Scrape Apartments.com rentals via Playwright.

Uses headless Firefox to bypass Apartments.com anti-bot detection,
extracts listing cards from search results, normalizes to the standard
listing schema, and saves to .tmp/apartments_raw.json.

Usage:
    python tools/scrape_apartments.py              # default: up to 100 listings
    python tools/scrape_apartments.py --max 50     # limit total listings
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SEARCH_URL = "https://www.apartments.com/san-francisco-ca/1-bedrooms-2500-to-3500/"
MAX_PAGES = 5
DEFAULT_MAX_ITEMS = 100


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
    """Extract first dollar amount from text like '$3,297+' or '$2,549'."""
    match = re.search(r"\$[\d,]+", text)
    if match:
        digits = re.sub(r"[^\d]", "", match.group())
        return int(digits) if digits else None
    return None


def _extract_card_data(card) -> dict | None:
    """Extract structured data from an article.placard element via JS."""
    return card.evaluate("""el => {
        const title = el.querySelector(".property-title");
        const addr = el.querySelector(".property-address");
        const amenities = el.querySelector(".property-amenities");
        return {
            listing_id: el.getAttribute("data-listingid") || "",
            url: el.getAttribute("data-url") || "",
            street: el.getAttribute("data-streetaddress") || "",
            title: title ? title.innerText.trim() : "",
            address: addr ? addr.innerText.trim() : "",
            amenities: amenities ? amenities.innerText.trim() : "",
            full_text: el.innerText,
        };
    }""")


# ---------------------------------------------------------------------------
# Normalize card → standard schema
# ---------------------------------------------------------------------------

def normalize_listing(card_data: dict) -> dict | None:
    """Convert one Apartments.com card to our standard listing schema."""
    now = _now_iso()

    url = card_data.get("url", "")
    if not url:
        return None

    address = card_data.get("address", "")
    title = card_data.get("title", "")
    full_text = card_data.get("full_text", "")

    # Parse price from card text — look for "1 Bed\n$X,XXX" pattern
    price = _parse_price(full_text)

    # Amenities
    amenities = card_data.get("amenities", "")
    description = f"Amenities: {amenities}" if amenities else ""

    return {
        "listing_id": make_listing_id(url),
        "source": "apartments.com",
        "title": title,
        "url": url,
        "price": price,
        "bedrooms": 1.0,
        "bathrooms": None,
        "sqft": None,
        "address_raw": address,
        "address_normalized": normalize_address(address),
        "neighborhood": None,
        "lat": None,
        "lon": None,
        "description_full": description,
        "first_seen": now,
        "last_seen": now,
    }


# ---------------------------------------------------------------------------
# Scrape
# ---------------------------------------------------------------------------

def scrape_apartments(max_items: int = DEFAULT_MAX_ITEMS) -> list[dict]:
    """Scrape Apartments.com search results with Playwright Firefox."""
    from playwright.sync_api import sync_playwright

    print(f"[INFO] Starting Apartments.com scrape: 1BR, $2500-$3500, SF")
    print(f"[INFO] Max items: {max_items}")

    listings = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )
        page = context.new_page()

        # Load first page
        print(f"[INFO] Fetching: {SEARCH_URL}")
        try:
            resp = page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
        except Exception as exc:
            print(f"[ERROR] Initial page load failed: {exc}")
            browser.close()
            return []

        if resp and resp.status != 200:
            print(f"[ERROR] Got status {resp.status}, aborting")
            browser.close()
            return []

        for page_num in range(1, MAX_PAGES + 1):
            cards = page.query_selector_all("article.placard")
            print(f"[INFO] Page {page_num}: found {len(cards)} listing cards")

            if not cards:
                break

            for card in cards:
                if len(listings) >= max_items:
                    break

                card_data = _extract_card_data(card)
                if not card_data or not card_data.get("url"):
                    continue

                lid = card_data.get("listing_id", "")
                if lid in seen_ids:
                    continue
                seen_ids.add(lid)

                normalized = normalize_listing(card_data)
                if normalized:
                    listings.append(normalized)

            if len(listings) >= max_items:
                print(f"[INFO] Reached max items ({max_items}), stopping")
                break

            # Click next page button (stays in same session, avoids 403)
            next_btn = page.query_selector("a.next")
            if not next_btn:
                print(f"[INFO] No next page button, done")
                break

            pre_count = len(listings)
            try:
                # Dismiss any modal dialogs that may block clicks
                modal = page.query_selector(".modal.show .close, .modal.show [data-bs-dismiss]")
                if modal:
                    modal.click(timeout=2000)
                    page.wait_for_timeout(500)

                next_btn.click()
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as exc:
                print(f"[WARN] Next page navigation failed: {exc}")
                break

            # If no new listings were added from this page, stop
            if pre_count == len(listings) and page_num > 1:
                print(f"[INFO] No new listings on page {page_num + 1}, stopping")
                break

        browser.close()

    print(f"[INFO] Scraped {len(listings)} listings from Apartments.com")
    return listings


def save_raw(listings: list[dict], path: str = ".tmp/apartments_raw.json") -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(listings, fh, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved {len(listings)} listings → {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Apartments.com via Playwright")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_ITEMS, help="Max listings")
    args = parser.parse_args()

    listings = scrape_apartments(max_items=args.max)
    save_raw(listings)

    if listings:
        sample = listings[0]
        print(f"\nSample: {sample['title']} — ${sample['price']}")
