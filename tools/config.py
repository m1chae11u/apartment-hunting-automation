"""
config.py — Central configuration for the apartment hunting pipeline.

All search parameters, station coordinates, and neighborhood lists live here.
Every tool imports from this module instead of hardcoding values.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Search tiers — each tier defines a bedroom count and price range
# ---------------------------------------------------------------------------
SEARCHES = [
    {"bedrooms": 1, "min_price": 2500, "max_price": 3000},
    {"bedrooms": 2, "min_price": 3500, "max_price": 5000},
]

# ---------------------------------------------------------------------------
# Caltrain stations — search radius and distance filter
# ---------------------------------------------------------------------------
CALTRAIN_STATIONS = [
    {"name": "4th_king", "lat": 37.7762, "lon": -122.3942},
    {"name": "22nd_st", "lat": 37.7575, "lon": -122.3922},
]

MAX_CALTRAIN_MI = 1.0
SEARCH_DISTANCE_MI = 1

# ---------------------------------------------------------------------------
# Neighborhoods — only these are kept; everything else is rejected
# ---------------------------------------------------------------------------
VALID_NEIGHBORHOODS = ["SoMa", "South Beach", "Rincon Hill", "Mission Bay"]
