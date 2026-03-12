"""
group_buildings.py — Step 3: Group filtered listings into buildings via Claude CLI.

Reads .tmp/filtered_listings.json (accepted listings), calls `claude -p` to extract
building names and neighborhoods, then groups duplicate listings into one row per building.
Outputs .tmp/grouped_buildings.json.

Uses Claude Code CLI (claude -p) which runs on the user's Max subscription — no API key needed.
"""

import json
import subprocess
from pathlib import Path

TMP_DIR = Path(__file__).parent.parent / ".tmp"

# Valid neighborhood tabs in the Google Sheet
VALID_NEIGHBORHOODS = [
    "Mission Bay",
    "Design District",
    "SoMA",
    "South Beach",
    "Potrero Hill",
    "Dogpatch",
    "Mission",
]

PROMPT_TEMPLATE = """You are classifying apartment listings for a San Francisco apartment search.

For each listing below, extract:
1. **building_name**: The actual building/complex name if mentioned (e.g. "The Beacon", "Soma Residences"). If no building name is evident, use the street address.
2. **neighborhood**: Which SF neighborhood this is in. Must be one of: {neighborhoods}

If two or more listings are from the same building (same address), they should get the same building_name.

Return ONLY valid JSON — an array of objects with these fields:
- listing_id: (from input)
- building_name: string
- neighborhood: string (must be one of the valid options above)

Here are the listings:

{listings_json}"""


def build_prompt(listings: list[dict]) -> str:
    """Build the classification prompt with minimal listing data."""
    slim = []
    for l in listings:
        slim.append({
            "listing_id": l["listing_id"],
            "title": l["title"],
            "address_raw": l.get("address_raw", ""),
            "description_snippet": (l.get("description_full", "") or "")[:500],
            "price": l.get("price"),
            "url": l.get("url", ""),
        })

    return PROMPT_TEMPLATE.format(
        neighborhoods=", ".join(VALID_NEIGHBORHOODS),
        listings_json=json.dumps(slim, indent=2),
    )


def call_claude(prompt: str) -> str:
    """Call claude -p and return the response text."""
    env = {**subprocess.os.environ}
    env.pop("CLAUDECODE", None)  # allow running from inside Claude Code
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: {result.stderr}")
    return result.stdout.strip()


def parse_response(response: str) -> list[dict]:
    """Extract JSON array from Claude's response."""
    # Find JSON array in response (may have surrounding text)
    start = response.find("[")
    end = response.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON array found in response:\n{response}")
    return json.loads(response[start:end])


def group_into_buildings(listings: list[dict], classifications: list[dict]) -> list[dict]:
    """Group listings by building_name, producing one entry per building."""
    # Index classifications by listing_id
    cls_by_id = {c["listing_id"]: c for c in classifications}

    # Group listings by building_name
    buildings: dict[str, dict] = {}
    for listing in listings:
        lid = listing["listing_id"]
        cls = cls_by_id.get(lid)
        if not cls:
            print(f"  WARNING: no classification for listing {lid}, skipping")
            continue

        bname = cls["building_name"]
        if bname not in buildings:
            # First listing for this building — use its data
            price = listing.get("price")
            buildings[bname] = {
                "name": bname,
                "neighborhood": cls["neighborhood"],
                "address": listing.get("address_raw", ""),
                "price": f"${price:,}" if price else "",
                "url": listing.get("url", ""),
                "caltrain": f"{listing.get('nearest_caltrain_mi', '?')}mi to {listing.get('nearest_station', '?')}",
                "listings": 1,
            }
        else:
            buildings[bname]["listings"] += 1

    return list(buildings.values())


def main():
    filtered_path = TMP_DIR / "filtered_listings.json"
    with open(filtered_path) as f:
        data = json.load(f)

    accepted = data["accepted"]
    print(f"Loaded {len(accepted)} accepted listings")

    if not accepted:
        print("No listings to classify")
        output_path = TMP_DIR / "grouped_buildings.json"
        with open(output_path, "w") as f:
            json.dump([], f)
        return

    # Build prompt and call Claude
    prompt = build_prompt(accepted)
    print(f"Calling claude -p for building classification...")
    response = call_claude(prompt)

    # Parse and group
    classifications = parse_response(response)
    print(f"Got {len(classifications)} classifications")

    buildings = group_into_buildings(accepted, classifications)
    print(f"Grouped into {len(buildings)} unique buildings")

    # Save
    output_path = TMP_DIR / "grouped_buildings.json"
    with open(output_path, "w") as f:
        json.dump(buildings, f, indent=2)
    print(f"\nSaved to {output_path}")

    for b in buildings:
        print(f"  {b['name']} ({b['neighborhood']}) — {b['price']} — {b['listings']} listing(s)")


if __name__ == "__main__":
    main()
