"""
process.py — Step 2: Hard filters for apartment listings.

Loads raw scraped listings, computes Caltrain distances, applies hard filters,
and saves the survivors to .tmp/filtered_listings.json.
"""

import json
import re
from pathlib import Path
from geopy.distance import geodesic

# Caltrain stations
STATIONS = {
    "4th_king": (37.7762, -122.3942),
    "22nd_st": (37.7575, -122.3922),
}

# Hard filter thresholds
MAX_PRICE = 3500
MAX_CALTRAIN_MI = 1.0


def calc_caltrain_distance(lat: float, lon: float) -> dict:
    """Geodesic distance to each Caltrain station."""
    point = (lat, lon)
    distances = {
        name: geodesic(point, coords).miles
        for name, coords in STATIONS.items()
    }
    nearest = min(distances, key=distances.get)
    return {
        "dist_4th_king_mi": round(distances["4th_king"], 3),
        "dist_22nd_st_mi": round(distances["22nd_st"], 3),
        "nearest_caltrain_mi": round(distances[nearest], 3),
        "nearest_station": nearest,
    }


def check_shared_laundry(description: str) -> bool:
    """Returns True if description explicitly mentions shared/coin-op laundry."""
    desc_lower = description.lower()
    shared_patterns = [
        r"laundry facilit",      # "laundry facilities" = shared
        r"coin[\s-]?op",
        r"shared laundry",
        r"laundry room",
        r"laundromat",
        r"community laundry",
        r"on-?site laundry",
    ]
    # But NOT if in-unit laundry is also mentioned (takes precedence)
    inunit_patterns = [
        r"in[\s-]?unit (washer|laundry)",
        r"washer[/ &]+dryer in",
        r"in[\s-]?home laundry",
        r"washer[/ &]+dryer included",
        r"full[\s-]?size washer",
    ]
    has_shared = any(re.search(p, desc_lower) for p in shared_patterns)
    has_inunit = any(re.search(p, desc_lower) for p in inunit_patterns)
    # Only reject if shared is mentioned AND in-unit is NOT mentioned
    return has_shared and not has_inunit


def check_ground_floor(description: str) -> bool:
    """Returns True if description suggests ground/first floor unit."""
    desc_lower = description.lower()
    ground_patterns = [
        r"ground\s*floor",
        r"first\s*floor",
        r"1st\s*floor",
        r"street[\s-]?level",
    ]
    return any(re.search(p, desc_lower) for p in ground_patterns)


def apply_hard_filters(listings: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Apply hard filters. Returns (accepted, rejected) lists.
    Each rejected listing gets a 'reject_reason' field.
    """
    accepted = []
    rejected = []

    for listing in listings:
        reasons = []

        # 1. Price filter
        price = listing.get("price")
        if price is not None and price > MAX_PRICE:
            reasons.append(f"price ${price} > ${MAX_PRICE}")

        # 2. Caltrain distance
        lat, lon = listing.get("lat"), listing.get("lon")
        if lat is not None and lon is not None:
            dist_info = calc_caltrain_distance(lat, lon)
            listing.update(dist_info)
            if dist_info["nearest_caltrain_mi"] > MAX_CALTRAIN_MI:
                reasons.append(f"caltrain {dist_info['nearest_caltrain_mi']}mi > {MAX_CALTRAIN_MI}mi")
        else:
            listing["nearest_caltrain_mi"] = None
            reasons.append("no lat/lon — cannot verify caltrain distance")

        # 3. Ground floor
        desc = listing.get("description_full", "")
        if check_ground_floor(desc):
            reasons.append("ground floor")

        # 4. Shared laundry
        if check_shared_laundry(desc):
            reasons.append("shared laundry")

        if reasons:
            listing["reject_reason"] = "; ".join(reasons)
            listing["auto_rejected"] = True
            rejected.append(listing)
        else:
            listing["auto_rejected"] = False
            listing["reject_reason"] = None
            accepted.append(listing)

    return accepted, rejected


def main():
    raw_path = Path(__file__).parent.parent / ".tmp" / "craigslist_raw.json"
    with open(raw_path) as f:
        listings = json.load(f)

    print(f"Loaded {len(listings)} raw listings")
    print()

    accepted, rejected = apply_hard_filters(listings)

    # Summary
    print(f"=== HARD FILTER RESULTS ===")
    print(f"Accepted: {len(accepted)}")
    print(f"Rejected: {len(rejected)}")
    print()

    # Rejection breakdown
    reason_counts = {}
    for r in rejected:
        for reason in r["reject_reason"].split("; "):
            key = reason.split(" ")[0]  # first word as category
            reason_counts[key] = reason_counts.get(key, 0) + 1
    print("Rejection reasons:")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    print()

    # Show accepted listings
    print("=== ACCEPTED LISTINGS ===")
    for i, listing in enumerate(accepted, 1):
        addr = listing.get("address_raw", "unknown")
        price = listing.get("price", "?")
        dist = listing.get("nearest_caltrain_mi", "?")
        station = listing.get("nearest_station", "?")
        title = listing.get("title", "")[:60]
        print(f"{i:2}. ${price:,} | {dist}mi to {station} | {addr}")
        print(f"    {title}")
        print()

    # Show rejected with reasons
    print("=== REJECTED LISTINGS ===")
    for listing in rejected:
        addr = listing.get("address_raw", "unknown")
        price = listing.get("price", "?")
        reason = listing.get("reject_reason", "")
        print(f"  ${price:,} | {addr} — {reason}")

    # Save filtered results
    out_path = Path(__file__).parent.parent / ".tmp" / "filtered_listings.json"
    output = {"accepted": accepted, "rejected": rejected}
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
