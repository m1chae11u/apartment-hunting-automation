from __future__ import annotations

"""
score.py — Filter listings by hard constraints and score them by user preferences.

Part of the WAT framework apartment hunting automation.

Hard constraints (auto-reject):
  - Price > $3,500/mo
  - Ground floor unit
  - Laundry explicitly shared/coin-op (not merely unmentioned)
  - More than 1 mile from nearest Caltrain station

Scoring model (0–100 total):
  - Urban Feel : max 35 pts
  - Price      : max 25 pts
  - Caltrain   : max 20 pts
  - Amenities  : max 20 pts
"""

import re


# ---------------------------------------------------------------------------
# Module-level keyword constants
# ---------------------------------------------------------------------------

VIEW_KEYWORDS: list[str] = [
    "city view",
    "skyline",
    "bay view",
    "panoramic",
    "view of the bay",
    "san francisco view",
    "downtown view",
    "water view",
    "bridge view",
    "stunning view",
    "amazing view",
    "beautiful view",
    "views of",
]

INUNIT_LAUNDRY_KEYWORDS: list[str] = [
    "in-unit laundry",
    "in unit laundry",
    "washer/dryer in unit",
    "w/d in unit",
    "w/d included",
    "washer and dryer",
    "in-unit w/d",
    "laundry in unit",
]

SHARED_LAUNDRY_KEYWORDS: list[str] = [
    "shared laundry",
    "coin-op",
    "laundromat",
    "laundry room",
    "laundry in building",
    "coin laundry",
    "shared washer",
    "no laundry",
]

GROUND_FLOOR_KEYWORDS: list[str] = [
    "ground floor",
    "1st floor",
    "first floor",
]

DOORMAN_KEYWORDS: list[str] = [
    "doorman",
    "concierge",
    "attended lobby",
    "front desk",
    "24-hour door",
]

NEW_CONSTRUCTION_KEYWORDS: list[str] = [
    "new construction",
    "newly built",
    "brand new",
    "modern building",
    "newly constructed",
    "new build",
]

GYM_KEYWORDS: list[str] = [
    "gym",
    "fitness center",
    "fitness room",
    "workout room",
    "exercise room",
]

PET_FRIENDLY_KEYWORDS: list[str] = [
    "pet friendly",
    "pet-friendly",
    "pets allowed",
    "cats ok",
    "dogs ok",
    "cats allowed",
    "dogs allowed",
    "pets ok",
    "pet ok",
]

ROOFTOP_KEYWORDS: list[str] = [
    "rooftop",
    "roof deck",
    "roof top",
    "rooftop deck",
    "rooftop terrace",
]

BALCONY_KEYWORDS: list[str] = [
    "balcony",
    "private deck",
    "private patio",
    "private terrace",
    "juliet balcony",
]

# Regex patterns for floor number extraction
_FLOOR_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bfloor\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(\d+)(?:st|nd|rd|th)[- ]floor\b", re.IGNORECASE),
]

# Unit number heuristic: "unit NNNN" or "#NNNN" where NNNN is 3+ digits
_UNIT_PATTERN: re.Pattern = re.compile(
    r"(?:unit\s*#?|#\s*)(\d{3,4})\b", re.IGNORECASE
)

# Year patterns indicating new construction: "built in 201X" or "built in 202X"
_NEW_CONSTRUCTION_YEAR: re.Pattern = re.compile(
    r"\bbuilt\s+in\s+20[12]\d\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# NLP / Regex extraction helpers
# ---------------------------------------------------------------------------

def _contains_any(text: str, keywords: list[str]) -> bool:
    """Return True if any keyword appears in text (case-insensitive)."""
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def parse_floor_number(description: str, title: str = "") -> int | None:
    """
    Extract the floor number from a listing description and optional title.

    Tries explicit floor patterns first, then a unit-number heuristic.
    Special cases:
      - "ground floor", "1st floor", "first floor" → 1
      - "penthouse" → 20 (symbolic high floor)

    Args:
        description: Full listing description text.
        title: Optional listing title (also searched).

    Returns:
        Integer floor number, or None if no floor information is found.
    """
    combined = f"{title} {description}"
    lower = combined.lower()

    # Special string cases
    if any(kw in lower for kw in GROUND_FLOOR_KEYWORDS):
        return 1
    if "penthouse" in lower:
        return 20

    # Explicit floor mentions
    for pattern in _FLOOR_PATTERNS:
        match = pattern.search(combined)
        if match:
            floor = int(match.group(1))
            if 1 <= floor <= 80:
                return floor

    # Unit number heuristic: first digit(s) before the last two digits = floor
    unit_match = _UNIT_PATTERN.search(combined)
    if unit_match:
        unit_str = unit_match.group(1)
        if len(unit_str) >= 3:
            floor_digits = unit_str[:-2]
            floor = int(floor_digits)
            if 1 <= floor <= 80:
                return floor

    return None


def detect_view(description: str) -> bool:
    """Return True if the description mentions a notable view."""
    return _contains_any(description, VIEW_KEYWORDS)


def detect_inunit_laundry(description: str) -> bool | None:
    """
    Determine in-unit laundry status from the description.

    Returns:
        True  — in-unit laundry confirmed
        False — laundry is explicitly shared / not in-unit
        None  — no laundry information found
    """
    lower = description.lower()
    has_inunit = any(kw in lower for kw in INUNIT_LAUNDRY_KEYWORDS)
    has_shared = any(kw in lower for kw in SHARED_LAUNDRY_KEYWORDS)

    if has_inunit:
        return True
    if has_shared:
        return False
    return None


def detect_ground_floor(description: str, floor_number: int | None) -> bool:
    """Return True if the unit is on the ground floor."""
    if floor_number == 1:
        return True
    return _contains_any(description, GROUND_FLOOR_KEYWORDS)


def detect_doorman(description: str) -> bool:
    """Return True if the building has a doorman or concierge service."""
    return _contains_any(description, DOORMAN_KEYWORDS)


def detect_new_construction(description: str, title: str = "") -> bool:
    """Return True if the listing indicates new / modern construction."""
    combined = f"{title} {description}"
    if _contains_any(combined, NEW_CONSTRUCTION_KEYWORDS):
        return True
    if _NEW_CONSTRUCTION_YEAR.search(combined):
        return True
    return False


def detect_gym(description: str) -> bool:
    """Return True if the building has a gym or fitness facility."""
    return _contains_any(description, GYM_KEYWORDS)


def detect_pet_friendly(description: str) -> bool:
    """Return True if the listing is pet-friendly."""
    return _contains_any(description, PET_FRIENDLY_KEYWORDS)


def detect_rooftop(description: str) -> bool:
    """Return True if the building has a rooftop or roof deck."""
    return _contains_any(description, ROOFTOP_KEYWORDS)


def detect_balcony(description: str) -> bool:
    """Return True if the unit has a balcony or private outdoor space."""
    return _contains_any(description, BALCONY_KEYWORDS)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def extract_features(listing: dict) -> dict:
    """
    Run all NLP/regex detection functions on the listing and annotate it.

    Reads `listing["description_full"]` and `listing["title"]`.
    Writes feature fields back into the listing dict in place.

    Args:
        listing: Listing dict. Must have "description_full"; "title" is optional.

    Returns:
        The same listing dict with feature fields populated.
    """
    description = listing.get("description_full") or ""
    title = listing.get("title") or ""

    # Floor and ground-floor detection
    floor_number = parse_floor_number(description, title)
    # Preserve an existing floor_number if the listing already has one and
    # the NLP extraction returned None (e.g. set by a prior enrichment step).
    if floor_number is None and listing.get("floor_number") is not None:
        floor_number = listing["floor_number"]

    listing["floor_number"] = floor_number
    listing["is_ground_floor"] = detect_ground_floor(description, floor_number)
    listing["has_view"] = detect_view(description)
    listing["has_inunit_laundry"] = detect_inunit_laundry(description)
    listing["has_doorman"] = detect_doorman(description)
    listing["is_new_construction"] = detect_new_construction(description, title)
    listing["has_gym"] = detect_gym(description)
    listing["is_pet_friendly"] = detect_pet_friendly(description)
    listing["has_rooftop"] = detect_rooftop(description)
    listing["has_balcony"] = detect_balcony(description)

    return listing


# ---------------------------------------------------------------------------
# Hard filters
# ---------------------------------------------------------------------------

def apply_hard_filters(listing: dict) -> tuple[bool, str | None]:
    """
    Evaluate whether a listing should be auto-rejected.

    Checks are applied in priority order:
      1. Price > $3,500/mo
      2. Ground floor unit
      3. Laundry explicitly shared/coin-op (has_inunit_laundry == False)
      4. More than 1.0 mile from nearest Caltrain station

    Args:
        listing: Listing dict with feature fields already populated.

    Returns:
        (is_rejected, reason_string) where reason_string is None if not rejected.
    """
    price = listing.get("price")
    if price is not None and price > 3500:
        return True, f"over budget (${price:,.0f})"

    if listing.get("is_ground_floor"):
        return True, "ground floor unit"

    if listing.get("has_inunit_laundry") is False:
        return True, "no in-unit laundry"

    nearest_mi = listing.get("nearest_caltrain_mi")
    if nearest_mi is not None and nearest_mi > 1.0:
        return True, f"too far from Caltrain ({nearest_mi:.2f} mi)"

    return False, None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_urban(listing: dict) -> float:
    """
    Compute the Urban Feel score (0–35 pts).

    Floor base + additive bonuses, capped at 35.
    """
    floor = listing.get("floor_number")

    if listing.get("is_ground_floor"):
        base = 0
    elif floor is None:
        base = 5
    elif floor >= 11:
        base = 35
    elif floor >= 7:
        base = 22
    elif floor >= 4:
        base = 15
    else:
        # floor 2 or 3
        base = 8

    bonus = 0
    if listing.get("has_view"):
        bonus += 8
    if listing.get("has_doorman"):
        bonus += 5
    if listing.get("is_new_construction"):
        bonus += 5

    return min(35.0, float(base + bonus))


def _score_price(listing: dict) -> float:
    """
    Compute the Price score (0–25 pts).

    Formula: max(0, 25 * (3500 - price) / 1000)
    At $2,500 → 25 pts; at $3,500 → 0 pts; above $3,500 → 0 pts (and rejected).
    """
    price = listing.get("price")
    if price is None:
        return 0.0
    return max(0.0, 25.0 * (3500.0 - price) / 1000.0)


def _score_caltrain(listing: dict) -> float:
    """
    Compute the Caltrain Proximity score (0–20 pts).
    """
    mi = listing.get("nearest_caltrain_mi")
    if mi is None:
        return 0.0
    if mi < 0.25:
        return 20.0
    if mi < 0.5:
        return 16.0
    if mi < 0.75:
        return 10.0
    if mi <= 1.0:
        return 5.0
    return 0.0


def _score_amenities(listing: dict) -> float:
    """
    Compute the Amenities score (0–20 pts).
    """
    score = 0.0
    if listing.get("has_gym"):
        score += 6.0
    if listing.get("is_pet_friendly"):
        score += 5.0
    if listing.get("has_rooftop"):
        score += 5.0
    if listing.get("has_balcony"):
        score += 4.0
    return score


def score_listing(listing: dict) -> dict:
    """
    Score a listing and set rejection/score fields.

    Assumes `extract_features` has already been called on the listing.
    Populates:
      - auto_rejected (bool)
      - reject_reason (str | None)
      - score_urban   (float)
      - score_price   (float)
      - score_caltrain (float)
      - score_amenities (float)
      - score_total   (float)

    Args:
        listing: Feature-annotated listing dict.

    Returns:
        The same listing dict with scoring fields added.
    """
    is_rejected, reason = apply_hard_filters(listing)
    listing["auto_rejected"] = is_rejected
    listing["reject_reason"] = reason

    listing["score_urban"] = round(_score_urban(listing), 2)
    listing["score_price"] = round(_score_price(listing), 2)
    listing["score_caltrain"] = round(_score_caltrain(listing), 2)
    listing["score_amenities"] = round(_score_amenities(listing), 2)

    listing["score_total"] = round(
        listing["score_urban"]
        + listing["score_price"]
        + listing["score_caltrain"]
        + listing["score_amenities"],
        2,
    )

    return listing


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_listings(listings: list[dict]) -> list[dict]:
    """
    Run feature extraction and scoring on every listing, then sort results.

    Sorting: non-rejected listings descend by score_total, followed by
    rejected listings (also descending by score_total for easy review).

    Args:
        listings: List of raw listing dicts.

    Returns:
        Sorted list of fully annotated listing dicts.
    """
    scored = [score_listing(extract_features(listing)) for listing in listings]

    # Stable sort: accepted first (auto_rejected=False sorts before True),
    # then descending score_total within each group.
    scored.sort(key=lambda l: (l["auto_rejected"], -l["score_total"]))
    return scored


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    mock_listing = {
        "title": "Stunning 15th Floor Unit at Lumina – Brand New Construction",
        "address_normalized": "201 Folsom St, San Francisco, CA",
        "price": 3200,
        "nearest_caltrain_mi": 0.35,
        "description_full": (
            "Welcome to this beautiful 2BR/2BA residence on the 15th floor of "
            "Lumina, a newly constructed luxury high-rise in SoMa. "
            "Enjoy breathtaking panoramic city views and bay views from your "
            "private balcony. The unit features washer and dryer in unit, "
            "floor-to-ceiling windows, and a modern chef's kitchen. "
            "Building amenities include a 24-hour concierge, state-of-the-art "
            "fitness center, rooftop deck, and pets allowed. "
            "Built in 2019. Walk to Caltrain in minutes."
        ),
    }

    print("=== score.py smoke test ===\n")
    print("Input listing:")
    print(f"  title  : {mock_listing['title']}")
    print(f"  price  : ${mock_listing['price']:,}/mo")
    print(f"  caltrain: {mock_listing['nearest_caltrain_mi']} mi\n")

    result = score_listing(extract_features(mock_listing))

    print("Extracted features:")
    feature_keys = [
        "floor_number", "is_ground_floor", "has_view", "has_inunit_laundry",
        "has_doorman", "is_new_construction", "has_gym", "is_pet_friendly",
        "has_rooftop", "has_balcony",
    ]
    for k in feature_keys:
        print(f"  {k:<22} : {result[k]}")

    print("\nScoring:")
    print(f"  auto_rejected   : {result['auto_rejected']}")
    print(f"  reject_reason   : {result['reject_reason']}")
    print(f"  score_urban     : {result['score_urban']:5.2f} / 35")
    print(f"  score_price     : {result['score_price']:5.2f} / 25")
    print(f"  score_caltrain  : {result['score_caltrain']:5.2f} / 20")
    print(f"  score_amenities : {result['score_amenities']:5.2f} / 20")
    print(f"  score_total     : {result['score_total']:5.2f} / 100")

    # Also exercise process_listings with a second (rejected) listing
    rejected_listing = {
        "title": "Cozy Studio – Ground Floor",
        "address_normalized": "999 Mission St, San Francisco, CA",
        "price": 3800,
        "nearest_caltrain_mi": 0.2,
        "description_full": (
            "Ground floor studio near transit. Shared laundry in building."
        ),
    }

    print("\n=== process_listings() with two listings ===\n")
    batch = process_listings([rejected_listing, mock_listing])
    for i, listing in enumerate(batch, 1):
        tag = "REJECTED" if listing["auto_rejected"] else "ACCEPTED"
        print(
            f"  [{i}] {tag:8s}  score={listing['score_total']:5.2f}"
            f"  reason={listing.get('reject_reason') or '—'}"
            f"  title={listing['title']!r}"
        )
