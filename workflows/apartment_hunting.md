# SF Apartment Hunting — Master SOP

## Objective

Find 1-bedroom apartments in San Francisco within 1 mile of a Caltrain station (4th & King or 22nd St) that match Mikel's preferences. Graduating from Berkeley in May 2026, targeting move-in around that date. Run twice daily, surface the best options via Google Sheets and email digest.

---

## Hard Constraints (Auto-Reject if Violated)

These are non-negotiable. A listing is rejected the moment it triggers any one of these:

| Constraint | Rule |
|---|---|
| Price | Must be $2,500–$3,500/mo. Hard ceiling is **$3,500** — reject anything above, no exceptions. |
| Bedrooms | 1 bedroom only. |
| Floor | No ground floor units. Reject if `is_ground_floor = True`. |
| Laundry | Reject only if laundry is **explicitly shared** (coin-op, shared laundry room, laundromat). If laundry isn't mentioned, do NOT reject — treat as unknown. |
| Caltrain | Must be within **1.0 mile** of 4th & King (37.7762, -122.3942) OR 22nd St (37.7575, -122.3922). Listings over 1.0 mi from both stations are auto-rejected. |

---

## Preferences (Used for Scoring)

Priority order, highest to lowest:

1. **Urban / high-rise vibe** — This is the top priority. High floor (11+), city/skyline/bay views, modern or newly constructed buildings, doorman/concierge. Mikel wants to feel like he's in the city, not in a flat.
2. **Price** — Lower is better within the $2,500–$3,500 band. Every dollar counts.
3. **Caltrain proximity** — Closer is better. Walking distance (under 0.5 mi) is ideal.
4. **Amenities** — Nice to have: gym, pet-friendly, rooftop, balcony.

See `workflows/scoring_model.md` for the full point-by-point rubric.

---

## Move-In Timeline

- **Target**: May 2026 (Berkeley graduation)
- **Flexibility**: Late April to early June is acceptable
- When browsing listings, prefer ones with availability in this window. Craigslist listings showing immediate availability in early 2026 are still worth tracking — landlords often re-list closer to the date.

---

## Execution Sequence

Run the full pipeline in this order. Each step feeds into the next.

### Option A: Direct CLI (one-shot run)

```bash
cd /Users/mikel/Documents/automations/apartment-hunting
python tools/pipeline.py --run-once
```

### Option B: Via n8n HTTP trigger

The pipeline server must already be running:

```bash
python tools/pipeline.py --serve --port 8765
```

Then n8n sends:

```
POST http://localhost:8765/run
```

### Pipeline Steps (internal to `pipeline.py`)

1. **Scrape** — `scrape_craigslist()` fetches up to 360 listings across 3 paginated pages. Saves raw output to `.tmp/craigslist_raw.json`.
2. **Geocode** — `enrich_with_caltrain()` geocodes each listing's normalized address using Nominatim and calculates distance to both Caltrain stations. Rate-limited at 1.1 req/sec.
3. **Extract features** — `extract_features()` runs NLP/regex detection on the full description text: floor number, laundry status, views, doorman, gym, rooftop, etc.
4. **Score** — `process_listings()` applies hard filters then scores each listing (0–100). Auto-rejected listings are tagged but kept in the output for visibility.
5. **Deduplicate** — Fetches existing `listing_id` values from the Listings sheet (column A). Splits scored listings into new vs. already-seen.
6. **Write Sheets** — Appends new listings to the `Listings` sheet. Updates `last_seen` timestamp for re-scraped existing listings. Logs run stats to the `Run Log` sheet.
7. **Email digest** — Sends HTML email with top 10 new listings ranked by score. Gmail SMTP via App Password.
8. **Save scored output** — Writes `.tmp/scored_listings.json` for local inspection.

---

## Output Destinations

### Google Sheet
- **ID**: `1XMMKEQ_e3NobZbyi1NW58dM2nCRuiTyGpkDO-OgDlkY`
- **URL**: `https://docs.google.com/spreadsheets/d/1XMMKEQ_e3NobZbyi1NW58dM2nCRuiTyGpkDO-OgDlkY`
- **Sheets**:
  - `Listings` — one row per unique listing, columns defined in `sheets_writer.py::LISTINGS_HEADERS`
  - `Run Log` — one row per pipeline run with counts and errors

### Email Digest
- Sent to `EMAIL_TO` (falls back to `EMAIL_FROM` if not set)
- Subject format: `SF Apartments — N new listings [Morning/Afternoon/Evening] Mar 12`
- Shows top 10 accepted listings sorted by `score_total`, followed by rejected listings
- Scheduled at **12:00 PM** and **6:00 PM** daily via n8n

---

## n8n Schedule Configuration

The automation runs on a Schedule Trigger in n8n:

```
Workflow: SF Apartment Hunt
Trigger: Schedule — 12:00 PM and 6:00 PM (America/Los_Angeles)
Step 1: HTTP Request
  Method: POST
  URL: http://localhost:8765/run
  Response: JSON
```

To verify the server is reachable before a run:

```
GET http://localhost:8765/health
```

Expected response: `{"status": "ok", "timestamp": "..."}`

To check results of the last run without running again:

```
GET http://localhost:8765/last-run
```

---

## Error Recovery

### Scraping fails (403, empty results, parse error)

- Check `.tmp/craigslist_raw.json` — if it's empty or missing, the scraper got blocked or the page structure changed.
- Run manually to see the error: `python tools/scrape_craigslist.py`
- See `workflows/scraping_craigslist.md` for detailed diagnostics.
- If blocked: wait 30–60 minutes and retry. Do not hammer the site.
- Pipeline aborts early and saves an `"error"` status to `.tmp/last_run.json`. No Sheets write or email occurs.

### Geocoding fails for some listings

- Geocoding errors are non-fatal. The listing is kept but `nearest_caltrain_mi` will be `None`.
- Listings without a distance value score 0 pts on Caltrain and won't be auto-rejected on distance grounds (benefit of the doubt).
- If geocoding fails for most listings, check Nominatim availability. It's a free public service with occasional downtime.

### Sheets write fails

- Most likely cause: `credentials.json` missing, service account not shared on the spreadsheet, or Google API quota exceeded.
- The pipeline logs the error and continues to the email step — email still sends with whatever data was scored.
- To re-run Sheets write only, call `write_results()` directly using data from `.tmp/scored_listings.json`.
- Verify credentials: `python tools/sheets_writer.py` (prints column headers as a smoke test).

### Email fails

- Check `.env` for `EMAIL_FROM`, `EMAIL_TO`, `GMAIL_APP_PASSWORD`.
- Gmail App Password must be 16 characters (spaces optional). Regular Gmail password will not work.
- Enable 2-Step Verification on the Google account first, then generate an App Password at `https://myaccount.google.com/apppasswords`.
- Test standalone: `python tools/email_digest.py`

### Pipeline server not running (n8n HTTP call fails)

- n8n will show a connection refused error.
- Start the server: `python tools/pipeline.py --serve --port 8765`
- For persistent operation, consider running via `launchd` or a `screen` session.

---

## Phase 2 Sources (Not Yet Active)

When Craigslist inventory feels thin, expand to:

- **Apartments.com** — Playwright-based scraping. See `workflows/scraping_apartments_com.md` (to be created).
- **Zillow** — Requires ScraperAPI due to bot detection. See `workflows/scraping_zillow.md`.

To add a new source, implement a scraper that returns the canonical listing dict schema (same keys as `_empty_listing()` in `scrape_craigslist.py`), then add it as a step in `pipeline.py::run_pipeline()`.

---

## Setup Checklist (One-Time)

Complete these before the first run:

- [ ] **Python deps**: `pip install -r requirements.txt`
- [ ] **Google credentials**: Download service account JSON key from Google Cloud Console, save as `credentials.json` in project root. Share the Google Sheet with the service account email (Editor access).
- [ ] **`.env` file**: Create at project root with the following:
  ```
  GOOGLE_SHEETS_SPREADSHEET_ID=1XMMKEQ_e3NobZbyi1NW58dM2nCRuiTyGpkDO-OgDlkY
  GOOGLE_APPLICATION_CREDENTIALS=credentials.json
  EMAIL_FROM=you@gmail.com
  EMAIL_TO=you@gmail.com
  GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
  MAX_LISTINGS_PER_SOURCE=360
  PIPELINE_PORT=8765
  ```
- [ ] **Smoke test scraper**: `python tools/scrape_craigslist.py` — should save 5 listings to `.tmp/craigslist_raw.json`
- [ ] **Smoke test scorer**: `python tools/score.py` — should print a scored mock listing
- [ ] **Smoke test Sheets**: `python tools/sheets_writer.py` — should print column headers without error
- [ ] **Smoke test email**: `python tools/email_digest.py` — set EMAIL env vars first to actually send
- [ ] **Start pipeline server**: `python tools/pipeline.py --serve`
- [ ] **Configure n8n**: Add Schedule Trigger + HTTP Request node pointing to `localhost:8765/run`
- [ ] **First full run**: `python tools/pipeline.py --run-once` and verify Sheet has new rows

---

## Local File Reference

```
.tmp/craigslist_raw.json   — Raw scraped listings (pre-geocode, pre-score)
.tmp/scored_listings.json  — All scored listings from the last run
.tmp/last_run.json         — Run metadata: status, counts, errors, duration
```

These are disposable. Delete and re-generate as needed.
