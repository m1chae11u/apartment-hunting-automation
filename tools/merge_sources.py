"""
merge_sources.py — Merge and deduplicate listings from all sources.

Auto-discovers all *_raw.json files in .tmp/, deduplicates across sources,
and outputs all_raw.json. Adding a new scraper is as simple as writing
a new <source>_raw.json file.

Dedup strategy:
  1. Exact URL match (same listing on same site)
  2. Normalized address + similar price (within 10%) across sources —
     keep the listing with more data (more non-null fields)

Usage:
    python tools/merge_sources.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TMP_DIR = Path(__file__).parent.parent / ".tmp"

def _discover_sources() -> dict[str, Path]:
    """Auto-discover all *_raw.json source files in .tmp/."""
    sources = {}
    for path in sorted(TMP_DIR.glob("*_raw.json")):
        # Derive source name: craigslist_raw.json -> craigslist
        name = path.stem.replace("_raw", "")
        if name == "all":
            continue  # skip our own output
        sources[name] = path
    return sources

OUTPUT_PATH = TMP_DIR / "all_raw.json"


# ---------------------------------------------------------------------------
# Address normalization for cross-source dedup
# ---------------------------------------------------------------------------

def _normalize_for_dedup(address: str) -> str:
    """Aggressively normalize an address for comparison."""
    if not address:
        return ""
    addr = address.lower().strip()
    # Remove apartment/unit/suite designators
    addr = re.sub(r"\b(apt|unit|suite|ste|#)\s*[\w-]*", "", addr)
    # Remove common suffixes
    addr = re.sub(r"\b(street|st|avenue|ave|boulevard|blvd|drive|dr|road|rd|lane|ln|court|ct|place|pl|way)\b", "", addr)
    # Remove city/state/zip
    addr = re.sub(r",?\s*san\s+francisco.*$", "", addr)
    # Collapse whitespace and punctuation
    addr = re.sub(r"[^a-z0-9]", " ", addr)
    addr = " ".join(addr.split())
    return addr


def _richness(listing: dict) -> int:
    """Count non-null, non-empty fields as a measure of data richness."""
    count = 0
    for key, val in listing.items():
        if val is not None and val != "" and val != []:
            count += 1
    return count


def _prices_similar(p1: int | None, p2: int | None, tolerance: float = 0.10) -> bool:
    """True if prices are within tolerance of each other."""
    if p1 is None or p2 is None:
        return False
    if p1 == 0 or p2 == 0:
        return False
    ratio = abs(p1 - p2) / max(p1, p2)
    return ratio <= tolerance


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def load_source(source_name: str, path: Path) -> list[dict]:
    """Load listings from a source file, or return empty list if missing."""
    if not path.exists():
        print(f"[INFO] {source_name}: file not found ({path}), skipping")
        return []
    try:
        with open(path) as f:
            listings = json.load(f)
        print(f"[INFO] {source_name}: loaded {len(listings)} listings")
        return listings
    except (json.JSONDecodeError, IOError) as exc:
        print(f"[WARN] {source_name}: failed to load ({exc}), skipping")
        return []


def merge_and_dedup(all_listings: list[dict]) -> list[dict]:
    """Deduplicate listings across sources."""
    # Pass 1: exact URL dedup
    seen_urls: dict[str, int] = {}  # url → index in result
    result: list[dict] = []

    for listing in all_listings:
        url = listing.get("url", "").split("?")[0].lower().rstrip("/")
        if url in seen_urls:
            # Keep the richer one
            existing_idx = seen_urls[url]
            if _richness(listing) > _richness(result[existing_idx]):
                result[existing_idx] = listing
        else:
            seen_urls[url] = len(result)
            result.append(listing)

    url_dupes = len(all_listings) - len(result)
    if url_dupes:
        print(f"[INFO] Removed {url_dupes} exact URL duplicates")

    # Pass 2: cross-source address + price dedup
    # Build index of normalized addresses
    addr_index: dict[str, list[int]] = {}
    for idx, listing in enumerate(result):
        norm_addr = _normalize_for_dedup(listing.get("address_normalized", ""))
        if norm_addr and len(norm_addr) > 3:  # skip very short/empty addresses
            addr_index.setdefault(norm_addr, []).append(idx)

    to_remove: set[int] = set()
    for norm_addr, indices in addr_index.items():
        if len(indices) < 2:
            continue
        # For each pair from different sources, check price similarity
        for i in range(len(indices)):
            if indices[i] in to_remove:
                continue
            for j in range(i + 1, len(indices)):
                if indices[j] in to_remove:
                    continue
                li = result[indices[i]]
                lj = result[indices[j]]
                # Only dedup across different sources
                if li.get("source") == lj.get("source"):
                    continue
                if _prices_similar(li.get("price"), lj.get("price")):
                    # Keep the richer one
                    if _richness(li) >= _richness(lj):
                        to_remove.add(indices[j])
                    else:
                        to_remove.add(indices[i])

    if to_remove:
        print(f"[INFO] Removed {len(to_remove)} cross-source address duplicates")
        result = [r for idx, r in enumerate(result) if idx not in to_remove]

    return result


def main():
    all_listings: list[dict] = []
    source_counts: dict[str, int] = {}

    source_files = _discover_sources()
    if not source_files:
        print("[WARN] No *_raw.json source files found in .tmp/")
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump([], f)
        return

    print(f"[INFO] Discovered sources: {list(source_files.keys())}")

    for source_name, path in source_files.items():
        listings = load_source(source_name, path)
        source_counts[source_name] = len(listings)
        all_listings.extend(listings)

    print(f"\n[INFO] Total before dedup: {len(all_listings)}")

    merged = merge_and_dedup(all_listings)

    print(f"[INFO] Total after dedup: {len(merged)}")

    # Source breakdown after dedup
    final_counts: dict[str, int] = {}
    for listing in merged:
        src = listing.get("source", "unknown")
        final_counts[src] = final_counts.get(src, 0) + 1
    print("\n[INFO] Final source breakdown:")
    for src, count in sorted(final_counts.items()):
        orig = source_counts.get(src, 0)
        print(f"  {src}: {count} (was {orig})")

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"\n[INFO] Saved {len(merged)} merged listings → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
