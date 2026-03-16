# Step 6: Multi-Source Scraping Design

## Status: Design approved, ready for implementation

## Goal
Add Apartments.com and Zillow as listing sources alongside Craigslist. Zillow is especially important for condos (individual condo owners listing rentals).

## Decision: Apify
After researching Playwright, Crawl4AI, Firecrawl, and Apify, we chose **Apify** because:
- Pre-built scrapers already exist for both Apartments.com and Zillow
- Handles anti-bot/proxies/JS rendering in their cloud — no headless browser on Mac Mini
- ~$1 per 1,000 listings, free tier gives $5/month (plenty for our volume)
- Simple Python integration via `apify-client` package

Apify API token is stored in `.env` as `APIFY_API_TOKEN`.

## Architecture

### Current pipeline
```
scrape.py (CL) -> process.py -> group_buildings.py -> update_sheet.py -> notify.py
```

### New pipeline
```
scrape.py (CL)           -\
scrape_apartments.py      |-> merge_sources.py -> process.py -> group_buildings.py -> update_sheet.py -> notify.py
scrape_zillow.py         -/
```

### New files to create
1. **tools/scrape_apartments.py** — Calls Apify Apartments.com actor, normalizes output to standard listing schema, saves to `.tmp/apartments_raw.json`
2. **tools/scrape_zillow.py** — Calls Apify Zillow actor (with condo filter), normalizes output, saves to `.tmp/zillow_raw.json`
3. **tools/merge_sources.py** — Reads all three `*_raw.json` files, dedupes across sources (same address = same building), outputs `.tmp/all_raw.json`

### Files to modify
4. **tools/process.py** — Change input path from `.tmp/craigslist_raw.json` to `.tmp/all_raw.json`
5. **run_pipeline.sh** — Add the three new steps before process.py
6. **requirements.txt** — Add `apify-client`

### Standard listing schema (all scrapers must output this)
```json
{
  "listing_id": "md5 hash of canonical URL",
  "source": "craigslist|apartments.com|zillow",
  "title": "string",
  "url": "string",
  "price": 2700,
  "bedrooms": 1.0,
  "bathrooms": 1.0,
  "sqft": 650,
  "address_raw": "260 King Street",
  "address_normalized": "260 King Street, San Francisco, CA",
  "neighborhood": "South Beach",
  "lat": 37.7762,
  "lon": -122.3942,
  "description_full": "string",
  "first_seen": "ISO timestamp",
  "last_seen": "ISO timestamp"
}
```

### Apify actors to use
- **Apartments.com**: One of `parseforge/apartments-com-scraper`, `powerful_bachelor/apartments-com-scraper`, or `sovereigntaylor/apartments-scraper` (need to test which works best)
- **Zillow**: `maxcopell/zillow-scraper` or `eunit/zillow-scraper` (the maxcopell one is more established)

### Search parameters for both
- Location: San Francisco, CA
- Bedrooms: 1
- Price: $2,500 - $3,500
- Zillow: include property type "Condo" + "Apartment"

### Dedup strategy in merge_sources.py
- Primary: exact URL match (same listing on same site)
- Secondary: normalize address + compare — if two listings from different sources have the same normalized address and similar price (within 10%), treat as same listing and keep the one with more data

### run_pipeline.sh (new order)
```bash
echo "=== Step 1a: Scrape Craigslist ==="
python tools/scrape.py

echo "=== Step 1b: Scrape Apartments.com ==="
python tools/scrape_apartments.py

echo "=== Step 1c: Scrape Zillow ==="
python tools/scrape_zillow.py

echo "=== Step 1d: Merge Sources ==="
python tools/merge_sources.py

echo "=== Step 2: Hard Filters ==="
python tools/process.py
# ... rest unchanged
```

### Error handling
- If one Apify scraper fails (rate limit, credits exhausted, actor broken), the pipeline should continue with whatever sources succeeded
- merge_sources.py should handle missing files gracefully (e.g., if zillow_raw.json doesn't exist, just skip it)

## Implementation order
1. scrape_apartments.py (easier, test Apify integration)
2. scrape_zillow.py (similar pattern, add condo filter)
3. merge_sources.py
4. Update process.py input path
5. Update run_pipeline.sh
6. Update requirements.txt
7. Test locally, then push to Mac Mini

## Open questions
- Which specific Apify actor IDs work best? Need to test a few.
- Zillow actor may require Apify residential proxies (extra cost) — need to verify.
