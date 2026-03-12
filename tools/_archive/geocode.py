from __future__ import annotations

"""
geocode.py — Geocode apartment addresses and calculate distance to SF Caltrain stations.

Part of the WAT framework apartment hunting automation.
"""

import os
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.distance import geodesic

load_dotenv()

# --- Module-level geocoder setup ---

_rate_limit_seconds = float(os.getenv("GEOCODE_RATE_LIMIT_SECONDS", "1.1"))

_geolocator = Nominatim(user_agent="sf-apartment-hunter")
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=_rate_limit_seconds)

# --- Station coordinates ---

_STATIONS = {
    "4th_king": (
        float(os.getenv("CALTRAIN_4TH_KING_LAT", "37.7762")),
        float(os.getenv("CALTRAIN_4TH_KING_LON", "-122.3942")),
    ),
    "22nd_st": (
        float(os.getenv("CALTRAIN_22ND_ST_LAT", "37.7575")),
        float(os.getenv("CALTRAIN_22ND_ST_LON", "-122.3922")),
    ),
}


# --- Functions ---

def geocode_address(address_str: str) -> tuple[float, float] | tuple[None, None]:
    """
    Geocode an address string to (lat, lon).

    Appends ', San Francisco, CA' to the address if not already present to
    improve accuracy. Uses Nominatim with a module-level RateLimiter.

    Args:
        address_str: Human-readable address string.

    Returns:
        (lat, lon) as floats, or (None, None) if geocoding fails.
    """
    # Append SF context if missing
    normalized = address_str.strip()
    lower = normalized.lower()
    if "san francisco" not in lower and "sf" not in lower:
        normalized = f"{normalized}, San Francisco, CA"

    try:
        location = _geocode(normalized)
        if location is None:
            print(f"[geocode] WARNING: No result for address: '{normalized}'")
            return (None, None)
        return (location.latitude, location.longitude)
    except Exception as exc:
        print(f"[geocode] WARNING: Geocoding failed for '{normalized}': {exc}")
        return (None, None)


def calc_caltrain_distance(lat: float, lon: float) -> dict:
    """
    Calculate geodesic distance in miles from (lat, lon) to each SF Caltrain station.

    Args:
        lat: Latitude of the point of interest.
        lon: Longitude of the point of interest.

    Returns:
        Dict with keys:
            dist_4th_king_mi   — distance to 4th & King station (miles)
            dist_22nd_st_mi    — distance to 22nd St station (miles)
            nearest_caltrain_mi — distance to the nearest of the two (miles)
            nearest_station     — "4th_king" or "22nd_st"
    """
    point = (lat, lon)

    distances = {
        station: geodesic(point, coords).miles
        for station, coords in _STATIONS.items()
    }

    nearest_station = min(distances, key=distances.get)

    return {
        "dist_4th_king_mi": round(distances["4th_king"], 4),
        "dist_22nd_st_mi": round(distances["22nd_st"], 4),
        "nearest_caltrain_mi": round(distances[nearest_station], 4),
        "nearest_station": nearest_station,
    }


def enrich_with_caltrain(listing: dict) -> dict:
    """
    Geocode a listing's normalized address and add Caltrain distance fields.

    Reads `listing["address_normalized"]`, geocodes it, and merges the
    distance fields returned by calc_caltrain_distance() into the listing dict.
    If geocoding fails, all distance fields are set to None.

    Args:
        listing: Dict containing at least "address_normalized".

    Returns:
        The same listing dict, mutated in place, with distance fields added.
    """
    # Prefer existing lat/lon from source data (e.g. Craigslist JSON-LD)
    lat = listing.get("lat")
    lon = listing.get("lon")

    # Fall back to Nominatim geocoding if lat/lon missing
    if lat is None or lon is None:
        address = listing.get("address_normalized", "")
        lat, lon = geocode_address(address)

    if lat is None or lon is None:
        listing.update({
            "dist_4th_king_mi": None,
            "dist_22nd_st_mi": None,
            "nearest_caltrain_mi": None,
            "nearest_station": None,
        })
    else:
        listing.update(calc_caltrain_distance(lat, lon))

    return listing


# --- Smoke test ---

if __name__ == "__main__":
    test_address = "188 King St, San Francisco, CA"
    print(f"Testing geocode for: {test_address!r}")

    lat, lon = geocode_address(test_address)
    if lat is None:
        print("Geocoding failed — check network / Nominatim availability.")
    else:
        print(f"  Coordinates: ({lat}, {lon})")
        distances = calc_caltrain_distance(lat, lon)
        print(f"  4th & King distance : {distances['dist_4th_king_mi']} mi")
        print(f"  22nd St distance    : {distances['dist_22nd_st_mi']} mi")
        print(f"  Nearest station     : {distances['nearest_station']} ({distances['nearest_caltrain_mi']} mi)")
        print()
        print("Testing enrich_with_caltrain():")
        listing = {"address_normalized": test_address, "price": 3200}
        enriched = enrich_with_caltrain(listing)
        for key, val in enriched.items():
            print(f"  {key}: {val}")
