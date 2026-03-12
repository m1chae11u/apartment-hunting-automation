# Scoring Model Reference

## Overview

Every listing that passes hard filters receives a score from 0–100 across four categories. Scores are computed by `tools/score.py` and stored as `score_total`, `score_urban`, `score_price`, `score_caltrain`, and `score_amenities` on each listing dict.

**Total = Urban Feel (35) + Price (25) + Caltrain Proximity (20) + Amenities (20)**

---

## Auto-Reject Rules (Applied Before Scoring)

These are checked first, in priority order. A listing that hits any rule is tagged `auto_rejected = True` with a `reject_reason`. It still gets scored (for visibility) but is excluded from the "top listings" section of the email.

| Rule | Condition | Reason String |
|---|---|---|
| Over budget | `price > 3500` | `"over budget ($X)"` |
| Ground floor | `is_ground_floor == True` | `"ground floor unit"` |
| Shared laundry | `has_inunit_laundry == False` | `"no in-unit laundry"` |
| Too far from Caltrain | `nearest_caltrain_mi > 1.0` | `"too far from Caltrain (X.XX mi)"` |

**Important laundry nuance**: `has_inunit_laundry` is a three-way value:
- `True` — in-unit laundry confirmed (good)
- `False` — laundry explicitly described as shared/coin-op (reject)
- `None` — no laundry information found (do NOT reject — leave it in)

---

## Category 1: Urban Feel (Max 35 pts)

This is Mikel's top priority. High-rise vibes, city views, modern buildings, doorman service.

### Floor Base Score

| Floor | Points |
|---|---|
| 11 or higher | 35 |
| 7–10 | 22 |
| 4–6 | 15 |
| 2–3 | 8 |
| Ground floor (1) | 0 (also auto-rejected) |
| Unknown / not mentioned | 5 |

### Additive Bonuses

| Feature | Points | How Detected |
|---|---|---|
| City / skyline / bay view | +8 | `has_view = True` |
| Doorman / concierge | +5 | `has_doorman = True` |
| New / modern construction | +5 | `is_new_construction = True` |

**Cap**: Urban Feel score is capped at 35 even if bonuses push it higher.

**Example**: Floor 7 (22 pts) + city view (+8) + doorman (+5) = 35 pts (capped).

### Keyword Lists

**Views** (`VIEW_KEYWORDS`):
`city view`, `skyline`, `bay view`, `panoramic`, `view of the bay`, `san francisco view`, `downtown view`, `water view`, `bridge view`, `stunning view`, `amazing view`, `beautiful view`, `views of`

**Doorman** (`DOORMAN_KEYWORDS`):
`doorman`, `concierge`, `attended lobby`, `front desk`, `24-hour door`

**New construction** (`NEW_CONSTRUCTION_KEYWORDS`):
`new construction`, `newly built`, `brand new`, `modern building`, `newly constructed`, `new build`
Also matches: `built in 201X` or `built in 202X` (regex).

**Floor detection**: The scraper looks for explicit patterns like `floor 12`, `12th floor`, then falls back to unit number heuristics (e.g., unit 1205 → floor 12). `penthouse` maps to floor 20.

---

## Category 2: Price (Max 25 pts)

Linear interpolation between $2,500 (best) and $3,500 (worst allowed).

**Formula**: `max(0, 25 * (3500 - price) / 1000)`

| Price | Score |
|---|---|
| $2,500 | 25.0 pts |
| $2,750 | 18.75 pts |
| $3,000 | 12.5 pts |
| $3,250 | 6.25 pts |
| $3,500 | 0 pts |
| > $3,500 | 0 pts (also auto-rejected) |

Listings with no price (`price = None`) score 0 on this category.

---

## Category 3: Caltrain Proximity (Max 20 pts)

Distance to the nearest of the two tracked stations: 4th & King or 22nd St.

| Distance | Points |
|---|---|
| < 0.25 mi | 20 |
| 0.25–0.5 mi | 16 |
| 0.5–0.75 mi | 10 |
| 0.75–1.0 mi | 5 |
| > 1.0 mi | 0 (also auto-rejected) |

Listings where geocoding failed (`nearest_caltrain_mi = None`) score 0 and are not auto-rejected on distance grounds.

**Station coordinates**:
- 4th & King: 37.7762, -122.3942
- 22nd St: 37.7575, -122.3922

---

## Category 4: Amenities (Max 20 pts)

Additive — a listing can score all 20 pts if it has everything.

| Amenity | Points | How Detected |
|---|---|---|
| Gym / fitness center | 6 | `has_gym = True` |
| Pet-friendly | 5 | `is_pet_friendly = True` |
| Rooftop / roof deck | 5 | `has_rooftop = True` |
| Balcony / private outdoor space | 4 | `has_balcony = True` |

### Keyword Lists

**Gym** (`GYM_KEYWORDS`):
`gym`, `fitness center`, `fitness room`, `workout room`, `exercise room`

**Pet-friendly** (`PET_FRIENDLY_KEYWORDS`):
`pet friendly`, `pet-friendly`, `pets allowed`, `cats ok`, `dogs ok`, `cats allowed`, `dogs allowed`, `pets ok`, `pet ok`

**Rooftop** (`ROOFTOP_KEYWORDS`):
`rooftop`, `roof deck`, `roof top`, `rooftop deck`, `rooftop terrace`

**Balcony** (`BALCONY_KEYWORDS`):
`balcony`, `private deck`, `private patio`, `private terrace`, `juliet balcony`

---

## Score Interpretation Guide

| Score | Meaning |
|---|---|
| 80–100 | Excellent — strong match on all dimensions. Prioritize these. |
| 60–79 | Good — worth a serious look. Probably solid on 2–3 categories. |
| 40–59 | Worth a look — something checks out but there are notable gaps. |
| < 40 | Skip — likely weak on urban feel or far from Caltrain. |

In practice, a floor 11+ unit with a view near a Caltrain station at $2,800 will score around 85+. A floor 4 unit with no view at $3,400 and 0.8 mi from Caltrain will score around 38.

---

## How to Tune the Weights

All scoring constants live in `tools/score.py` as module-level variables. To adjust:

1. Open `tools/score.py`
2. Modify the relevant constants or thresholds in `_score_urban()`, `_score_price()`, `_score_caltrain()`, or `_score_amenities()`
3. Run `python tools/score.py` to see the smoke test output with the new weights
4. If the change feels right, update the tables in this document to match

**Do not change the auto-reject rules** without also updating `apply_hard_filters()` in `score.py` and the constraint table in `workflows/apartment_hunting.md`. These three places must stay in sync.

---

## Full Scoring Example

**Listing**: Floor 15 unit at a new high-rise, city view, doorman, gym, rooftop, pet-friendly. Price $3,100. 0.3 mi from 4th & King.

| Category | Calculation | Score |
|---|---|---|
| Urban Feel | Floor 15 → 35 base + view (+8) + doorman (+5) + new construction (+5) = 53 → **capped at 35** | 35.0 |
| Price | 25 * (3500 - 3100) / 1000 = 25 * 0.4 = **10.0** | 10.0 |
| Caltrain | 0.3 mi → **16.0** | 16.0 |
| Amenities | gym (6) + pet-friendly (5) + rooftop (5) = **16.0** | 16.0 |
| **Total** | | **77.0** |

**Result**: Good (60–79 range). Would rank higher if the price were lower.
