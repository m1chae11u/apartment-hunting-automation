# SF Apartment Hunting — Master SOP

## Objective

Find 1-bedroom apartments in San Francisco within 1 mile of a Caltrain station (4th & King or 22nd St) that match Mikel's preferences. Graduating from Berkeley in May 2026, targeting move-in around that date. Run twice daily on the Mac Mini, surface options via Google Sheets and email notifications.

---

## Hard Constraints (Auto-Reject if Violated)

These are non-negotiable. A listing is rejected the moment it triggers any one of these:

| Constraint | Rule |
|---|---|
| Price | Must be $2,500–$3,500/mo. Hard ceiling is **$3,500** — reject anything above, no exceptions. |
| Bedrooms | 1 bedroom only. |
| Floor | No ground floor units. Reject if description mentions ground/first floor. |
| Laundry | Reject only if laundry is **explicitly shared** (coin-op, shared laundry room, laundromat). If laundry isn't mentioned, do NOT reject — treat as unknown. |
| Caltrain | Must be within **1.0 mile** of 4th & King (37.7762, -122.3942) OR 22nd St (37.7575, -122.3922). |
| Lat/Lon | Listings without coordinates are rejected (cannot verify Caltrain distance). |

---

## Preferences

Priority order, highest to lowest:

1. **Urban / high-rise vibe** — High floor, city/skyline/bay views, modern buildings, doorman/concierge.
2. **Price** — Lower is better within the $2,500–$3,500 band.
3. **Caltrain proximity** — Closer is better. Walking distance (under 0.5 mi) is ideal.
4. **Amenities** — Nice to have: gym, pet-friendly, rooftop, balcony.

**Note:** Scoring is deliberately NOT automated. The pipeline surfaces and filters listings; Mikel evaluates and ranks them manually in the Google Sheet.

---

## Move-In Timeline

- **Target**: May 2026 (Berkeley graduation)
- **Flexibility**: Late April to early June is acceptable

---

## Data Sources

| Source | Method | Status |
|---|---|---|
| **Craigslist** | Direct scraping via requests + BeautifulSoup | Active |
| **Zillow** | Apify actor (`maxcopell/zillow-scraper`) | Active |
| **Apartments.com** | — | Dropped (anti-bot detection too aggressive for automated scraping) |

For Apartments.com, use their saved search + email alerts and browse manually.

---

## Pipeline Steps

Run via `bash run_pipeline.sh` or automatically via launchd on the Mac Mini.

```
Step 1a: Scrape Craigslist    → .tmp/craigslist_raw.json
Step 1b: Scrape Zillow        → .tmp/zillow_raw.json
Step 1c: Merge & Dedup        → .tmp/all_raw.json
Step 2:  Hard Filters         → .tmp/filtered_listings.json
Step 3:  Building Grouping    → .tmp/grouped_buildings.json  (uses claude -p)
Step 4:  Update Google Sheet  → Appends new buildings to neighborhood tabs
Step 5:  Email Notification   → Sends alert if new buildings found
```

### Step 1a: Scrape Craigslist (`tools/scrape.py`)
- Fetches SF 1BR rentals $2,500–$3,500 from Craigslist
- Extracts listings from JSON-LD on search pages, then fetches detail pages
- Rate-limited at 1 req/sec
- See `workflows/scraping_craigslist.md` for details

### Step 1b: Scrape Zillow (`tools/scrape_zillow.py`)
- Calls the `maxcopell/zillow-scraper` Apify actor
- Map bounds constrained to Caltrain corridor (SoMa → Dogpatch)
- Costs a few cents of Apify credit per run
- See `workflows/scraping_zillow.md` for details

### Step 1c: Merge & Dedup (`tools/merge_sources.py`)
- Loads all `*_raw.json` files from `.tmp/`
- Pass 1: Exact URL deduplication (same listing on same site)
- Pass 2: Cross-source address + price similarity (within 10%) dedup
- Keeps the listing with more non-null fields when deduping

### Step 2: Hard Filters (`tools/process.py`)
- Computes geodesic distance to both Caltrain stations
- Applies hard filters (price, ground floor, shared laundry, distance, missing coords)
- Each listing gets `dist_4th_king_mi`, `dist_22nd_st_mi`, `nearest_caltrain_mi`, `nearest_station`
- Output: `{accepted: [...], rejected: [...]}` with reject reasons

### Step 3: Building Grouping (`tools/group_buildings.py`)
- Calls `claude -p` (Claude Code CLI) to classify each listing's building name + neighborhood
- Valid neighborhoods: Mission Bay, Design District, SoMA, South Beach, Potrero Hill, Dogpatch, Mission
- Groups multiple listings at the same building into one row
- Requires Claude Max subscription on the machine running the pipeline

### Step 4: Update Sheet (`tools/update_sheet.py`)
- Opens the Google Sheet by ID
- Creates neighborhood tabs if they don't exist
- Headers in row 4: NAME | WEBSITE | RENT/MO | NOTES | GOOGLE RATING | Street View
- Appends new buildings (skips duplicates by name, case-insensitive)

### Step 5: Notify (`tools/notify.py`)
- If new buildings were added, sends an email listing them
- Gmail SMTP via App Password
- Subject: "Apartment Hunt: N new building(s) found"

---

## Scheduling

The pipeline runs via **launchd** on the Mac Mini at **12:00 PM** and **6:00 PM** daily.

Plist: `com.mikel.apartment-pipeline.plist` (installed to `~/Library/LaunchAgents/` on the Mini)

Logs:
- stdout: `.tmp/pipeline.log`
- stderr: `.tmp/pipeline.err`

To install on a new machine:
```bash
cp com.mikel.apartment-pipeline.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mikel.apartment-pipeline.plist
```

To run manually:
```bash
bash run_pipeline.sh
```

---

## Output Destinations

### Google Sheet
- **ID**: `1XMMKEQ_e3NobZbyi1NW58dM2nCRuiTyGpkDO-OgDlkY`
- **URL**: `https://docs.google.com/spreadsheets/d/1XMMKEQ_e3NobZbyi1NW58dM2nCRuiTyGpkDO-OgDlkY`
- **Structure**: One tab per neighborhood, buildings as rows

### Email
- Sent to `EMAIL_TO` when new buildings are found
- Includes building names, neighborhoods, prices, and a link to the Sheet

---

## Error Recovery

### Craigslist scraping fails
- Check `.tmp/craigslist_raw.json` — if empty, likely IP blocked
- Wait 30–60 minutes and retry. See `workflows/scraping_craigslist.md`

### Zillow scraping fails
- Pipeline continues (has `|| echo "[WARN]"` fallback)
- Check Apify dashboard for actor run status
- Check `APIFY_API_TOKEN` in `.env`

### Claude classification fails
- `group_buildings.py` halts with RuntimeError if Claude CLI fails
- Check that `claude` CLI is installed and the Max subscription is active

### Sheets write fails
- Check `credentials.json` exists and service account has Editor access to the sheet
- Check `GOOGLE_APPLICATION_CREDENTIALS` path in `.env`

### Email fails
- Check `EMAIL_FROM`, `EMAIL_TO`, `GMAIL_APP_PASSWORD` in `.env`
- Gmail App Password must be 16 chars. Regular password won't work.
- 2-Step Verification must be enabled on the Gmail account

---

## Environment Variables (`.env`)

```
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
EMAIL_FROM=you@gmail.com
EMAIL_TO=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
APIFY_API_TOKEN=apify_api_...
MAX_LISTINGS_PER_SOURCE=360
```

---

## Local File Reference

```
.tmp/craigslist_raw.json      — Raw Craigslist listings
.tmp/zillow_raw.json          — Raw Zillow listings
.tmp/all_raw.json             — Merged + deduplicated listings
.tmp/filtered_listings.json   — After hard filters (accepted + rejected)
.tmp/grouped_buildings.json   — Buildings grouped by name/neighborhood
.tmp/pipeline.log             — Last pipeline run stdout
.tmp/pipeline.err             — Last pipeline run stderr
```

All `.tmp/` files are disposable and regenerated each run.
