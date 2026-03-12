from __future__ import annotations

"""
deduplicate.py

Deduplicates apartment listings across multiple sources and across pipeline
runs. Part of the apartment-hunting WAT framework.

Deduplication strategy:
  - Primary key: listing_id (MD5 of canonical URL). Same URL = same listing.
  - Cross-source: same building/unit on different sources is detected via
    address similarity (rapidfuzz token_sort_ratio >= 90) AND price within $50.
    The listing with the richer (longer) description_full is kept.
  - Cross-run: listings whose listing_id already appears in Google Sheets are
    flagged as "updated" (caller should refresh last_seen) rather than inserted.

Usage (test mode):
    python tools/deduplicate.py
"""

import hashlib
import json
import os
import re
import string
from typing import Optional, Union

from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Address normalisation
# ---------------------------------------------------------------------------

_ABBREVIATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bst\b"),   "street"),
    (re.compile(r"\bave\b"),  "avenue"),
    (re.compile(r"\bblvd\b"), "boulevard"),
    (re.compile(r"\bdr\b"),   "drive"),
    (re.compile(r"\bpl\b"),   "place"),
    # Unit/apt identifiers — remove the label but keep any alphanumeric token
    # that follows (e.g. "apt 4b" → "4b", "unit 202" → "202")
    (re.compile(r"\b(?:apt|unit)\s*"), ""),
]

_REMOVE_PHRASES: list[re.Pattern] = [
    re.compile(r"\bsan francisco\b"),
    re.compile(r"\bca\b"),
    re.compile(r"\b\d{5}(?:-\d{4})?\b"),  # zip codes
]

_PUNCTUATION_TABLE = str.maketrans(string.punctuation, " " * len(string.punctuation))


def normalize_for_comparison(address: str) -> str:
    """
    Return a normalised address string suitable for fuzzy comparison.

    Transformations applied (in order):
      1. Lowercase
      2. Strip punctuation (replaced with spaces)
      3. Expand common street abbreviations
      4. Remove "apt" / "unit" labels (preserving the unit identifier itself)
      5. Remove "san francisco", "ca", and zip codes
      6. Collapse whitespace

    Examples
    --------
    >>> normalize_for_comparison("188 King St, Apt 4B, SF CA 94107")
    '188 king street 4b'
    >>> normalize_for_comparison("450 Townsend St Unit 202, San Francisco, CA 94107")
    '450 townsend street 202'
    """
    if not address:
        return ""

    text = address.lower()
    text = text.translate(_PUNCTUATION_TABLE)

    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)

    for pattern in _REMOVE_PHRASES:
        text = pattern.sub(" ", text)

    # Collapse all runs of whitespace to a single space
    text = " ".join(text.split())
    return text


# ---------------------------------------------------------------------------
# Within-batch deduplication
# ---------------------------------------------------------------------------

def _price_within(a: Optional[Union[int, float]], b: Optional[Union[int, float]], delta: float = 50.0) -> bool:
    """Return True when both prices are known and differ by at most *delta* dollars."""
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= delta


def deduplicate_within_batch(listings: list[dict]) -> list[dict]:
    """
    Remove duplicate listings from a single batch before writing to Sheets.

    Two kinds of duplicates are handled:

    1. **Same listing_id** — identical canonical URL, regardless of source.
       The first occurrence is kept.

    2. **Cross-source duplicates** — different source, but address similarity
       >= 90 (rapidfuzz token_sort_ratio on normalised addresses) *and* price
       within $50. The listing with the longer ``description_full`` is kept.

    Parameters
    ----------
    listings:
        Raw list of listing dicts produced by scraper(s).

    Returns
    -------
    list[dict]
        Deduplicated list preserving the original relative ordering of
        survivors.
    """
    # --- Pass 1: deduplicate by listing_id (same source / same URL) ----------
    seen_ids: set[str] = set()
    id_deduped: list[dict] = []
    for listing in listings:
        lid = listing.get("listing_id")
        if lid and lid in seen_ids:
            continue
        if lid:
            seen_ids.add(lid)
        id_deduped.append(listing)

    # --- Pass 2: cross-source fuzzy address + price dedup --------------------
    # We build the result list incrementally. For each candidate we check
    # whether it is a near-duplicate of any already-accepted listing. If it is,
    # we replace the accepted listing when the candidate has a richer
    # description; otherwise we discard the candidate.

    accepted: list[dict] = []
    # Pre-compute normalised addresses for accepted listings (kept in sync).
    accepted_norm: list[str] = []

    for candidate in id_deduped:
        c_source = candidate.get("source", "")
        c_norm = normalize_for_comparison(candidate.get("address_normalized") or
                                          candidate.get("address_raw") or "")
        c_price = candidate.get("price")
        c_desc = candidate.get("description_full") or ""

        matched_idx: Optional[int] = None

        for idx, existing in enumerate(accepted):
            e_source = existing.get("source", "")

            # Cross-source check only — same source duplicates were handled
            # in pass 1 (by listing_id).  If for some reason two different
            # listing_ids share the same source, skip fuzzy matching to avoid
            # false positives (e.g. two different units in the same building).
            if c_source == e_source:
                continue

            # Skip if either normalised address is empty
            if not c_norm or not accepted_norm[idx]:
                continue

            similarity = fuzz.token_sort_ratio(c_norm, accepted_norm[idx])
            if similarity >= 90 and _price_within(c_price, existing.get("price")):
                matched_idx = idx
                break

        if matched_idx is None:
            # Genuinely distinct — add to accepted list
            accepted.append(candidate)
            accepted_norm.append(c_norm)
        else:
            # Duplicate found — keep whichever has the richer description
            existing_desc = accepted[matched_idx].get("description_full") or ""
            if len(c_desc) > len(existing_desc):
                accepted[matched_idx] = candidate
                accepted_norm[matched_idx] = c_norm

    return accepted


# ---------------------------------------------------------------------------
# Cross-run split
# ---------------------------------------------------------------------------

def split_new_vs_existing(
    listings: list[dict],
    existing_ids: set[str],
) -> tuple[list[dict], list[dict]]:
    """
    Split *listings* into truly new vs. already-known listings.

    Parameters
    ----------
    listings:
        Deduplicated batch of listings for the current pipeline run.
    existing_ids:
        Set of ``listing_id`` values already present in Google Sheets.

    Returns
    -------
    (new_listings, updated_listings)
        ``new_listings`` — listings not yet in Sheets; should be inserted.
        ``updated_listings`` — listings already in Sheets; caller should
        update their ``last_seen`` timestamp only.
    """
    new_listings: list[dict] = []
    updated_listings: list[dict] = []

    for listing in listings:
        lid = listing.get("listing_id")
        if lid and lid in existing_ids:
            updated_listings.append(listing)
        else:
            new_listings.append(listing)

    return new_listings, updated_listings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_deduplication(listings: list[dict], existing_ids: set[str]) -> dict:
    """
    Run the full deduplication pipeline for one pipeline run.

    Steps
    -----
    1. ``deduplicate_within_batch`` — remove intra-batch duplicates.
    2. ``split_new_vs_existing`` — separate new from already-known listings.

    Parameters
    ----------
    listings:
        All listings scraped in the current run (may contain duplicates).
    existing_ids:
        ``listing_id`` values already in Google Sheets.

    Returns
    -------
    dict with keys:
        ``new``             — truly new listings to insert into Sheets.
        ``updated``         — known listings seen again; update last_seen only.
        ``duplicate_count`` — number of listings dropped as within-batch dupes.
        ``total_input``     — number of listings passed in.
        ``total_output``    — ``len(new) + len(updated)``.
    """
    total_input = len(listings)

    deduped = deduplicate_within_batch(listings)
    duplicate_count = total_input - len(deduped)

    new_listings, updated_listings = split_new_vs_existing(deduped, existing_ids)

    return {
        "new": new_listings,
        "updated": updated_listings,
        "duplicate_count": duplicate_count,
        "total_input": total_input,
        "total_output": len(new_listings) + len(updated_listings),
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import hashlib as _hashlib

    def _make_id(url: str) -> str:
        canonical = url.split("?")[0].lower().rstrip("/")
        return _hashlib.md5(canonical.encode("utf-8")).hexdigest()

    # --- Mock listings -------------------------------------------------------

    # Listing A: Craigslist — 188 King St, Apt 4B
    listing_a = {
        "listing_id": _make_id("https://sfbay.craigslist.org/sfc/apa/123456"),
        "source": "craigslist",
        "url": "https://sfbay.craigslist.org/sfc/apa/123456",
        "price": 2950,
        "address_raw": "188 King St, Apt 4B",
        "address_normalized": "188 King St, Apt 4B, San Francisco, CA 94107",
        "description_full": "Bright 1BR near Caltrain. Hardwood floors, updated kitchen.",
    }

    # Listing B: Duplicate URL — same as A (different query params, same canonical)
    listing_b = {
        "listing_id": _make_id("https://sfbay.craigslist.org/sfc/apa/123456?utm_source=feed"),
        "source": "craigslist",
        "url": "https://sfbay.craigslist.org/sfc/apa/123456?utm_source=feed",
        "price": 2950,
        "address_raw": "188 King St, Apt 4B",
        "address_normalized": "188 King St, Apt 4B, San Francisco, CA 94107",
        "description_full": "Bright 1BR near Caltrain. Hardwood floors, updated kitchen.",
    }

    # Listing C: Apartments.com — same building/unit as A, richer description
    listing_c = {
        "listing_id": _make_id("https://www.apartments.com/188-king-st-san-francisco-ca/abc123/"),
        "source": "apartments.com",
        "url": "https://www.apartments.com/188-king-st-san-francisco-ca/abc123/",
        "price": 2975,  # within $50 of A
        "address_raw": "188 King Street Apt 4B San Francisco CA 94107",
        "address_normalized": "188 King Street, Apt 4B, San Francisco, CA 94107",
        "description_full": (
            "Stunning 1-bedroom at 188 King Street. Hardwood floors, chef's kitchen, "
            "in-unit laundry, roof deck, steps from Caltrain and Giants stadium. "
            "Available immediately. Pets negotiable."
        ),
    }

    # Listing D: Genuinely new — different address and price
    listing_d = {
        "listing_id": _make_id("https://sfbay.craigslist.org/sfc/apa/999999"),
        "source": "craigslist",
        "url": "https://sfbay.craigslist.org/sfc/apa/999999",
        "price": 3200,
        "address_raw": "450 Townsend St, Unit 202",
        "address_normalized": "450 Townsend St, Unit 202, San Francisco, CA 94107",
        "description_full": "Spacious loft in SoMa. Exposed brick, parking included.",
    }

    # Simulate: listing_a was already seen in a previous run
    existing_ids: set[str] = {listing_a["listing_id"]}

    batch = [listing_a, listing_b, listing_c, listing_d]

    print("=" * 60)
    print("deduplicate.py — self-test")
    print("=" * 60)
    print(f"Input batch size : {len(batch)}")
    print(f"Existing IDs     : {len(existing_ids)}")
    print()

    result = run_deduplication(batch, existing_ids)

    print(f"total_input      : {result['total_input']}")
    print(f"duplicate_count  : {result['duplicate_count']}")
    print(f"total_output     : {result['total_output']}")
    print(f"  new            : {len(result['new'])}")
    print(f"  updated        : {len(result['updated'])}")
    print()

    print("NEW listings:")
    for l in result["new"]:
        print(f"  [{l['source']:15s}] {l['address_raw']!r:45s} ${l['price']}")

    print()
    print("UPDATED listings (last_seen refresh only):")
    for l in result["updated"]:
        print(f"  [{l['source']:15s}] {l['address_raw']!r:45s} ${l['price']}")

    print()
    print("normalize_for_comparison examples:")
    examples = [
        "188 King St, Apt 4B, SF CA 94107",
        "188 King Street Apt 4B San Francisco CA 94107",
        "450 Townsend St, Unit 202, San Francisco, CA 94107",
        "1234 Market Blvd, Apt 5, San Francisco CA 94102",
    ]
    for ex in examples:
        print(f"  {ex!r}")
        print(f"    → {normalize_for_comparison(ex)!r}")
