# Craigslist Scraping — SOP

## Overview

Craigslist is the primary data source. The scraper fetches up to 3 paginated search result pages, then visits each listing's detail page to extract the full description and housing attributes. Everything lives in `tools/scrape.py`.

---

## Target URLs

The scraper runs separate searches for each bedroom/price tier defined in `tools/config.py`:

**1BR search:**
```
https://sfbay.craigslist.org/search/sfc/apa?min_price=2500&max_price=3000&min_bedrooms=1&max_bedrooms=1&availabilityMode=0&sort=date
```

**2BR search:**
```
https://sfbay.craigslist.org/search/sfc/apa?min_price=3500&max_price=5000&min_bedrooms=2&max_bedrooms=2&availabilityMode=0&sort=date
```

Each URL is also parameterized with `&lat=...&lon=...&search_distance=1` for each Caltrain station, resulting in 4 search pages total (2 tiers x 2 stations).

Pagination appends `&start=0`, `&start=120`, `&start=240` (120 results per page, Craigslist default).

**Path breakdown**:
- `/sfc/` — San Francisco city only (not greater Bay Area)
- `/apa` — Apartments section
- `min_price` / `max_price` — server-side price filter (tier-specific)
- `min_bedrooms` / `max_bedrooms` — tier-specific (1 or 2)
- `sort=date` — newest first, so we see new listings quickly

---

## Parsing Strategy

### Search Page: JSON-LD (Preferred)

Craigslist embeds structured listing data directly in the page HTML as a JSON-LD block:

```html
<script id="ld_searchpage_results" type="application/ld+json">...</script>
```

The scraper locates this tag with:
```python
soup.find("script", {"id": "ld_searchpage_results", "type": "application/ld+json"})
```

The JSON structure is an `ItemList` with listings in `itemListElement`. Each item may wrap the real data in an `"item"` sub-key. Fields extracted: `url`, `name` (title), `offers.price`, `geo.latitude`, `geo.longitude`.

**Why JSON-LD over HTML parsing?** It's more stable than scraping list-view HTML elements, which Craigslist redesigns periodically. The structured data format changes far less often.

### Detail Page: HTML Selectors

Once we have a listing URL from the search page, we fetch the detail page and extract:

| Field | Selector | Notes |
|---|---|---|
| Full description | `#postingbody`, fallback `.userbody` | Strip `.print-information` and `.postinginfos` junk blocks first |
| Price (fallback) | `.price` | Only used if JSON-LD didn't provide a price |
| Address | `.mapaddress`, fallback `[data-address]` attribute | Raw string, then normalized |
| Neighborhood | `.breadcrumb a` (last `<a>` tag) | Falls back to area slug in URL path |
| Bedrooms / bathrooms / sqft | `.attrgroup span` | Parsed with regex: `1BR / 1Ba`, `850ft²` |

---

## Pagination

```python
pages_to_fetch = min(3, ceil(max_listings / 120))
```

With `MAX_LISTINGS_PER_SOURCE=360` (the default), the scraper fetches all 3 pages. Each page adds up to 120 listings, though duplicates and deleted listings reduce the actual count.

Pagination stops early if a search page returns zero results (e.g., we've exhausted the available inventory).

---

## Rate Limiting

**1 request per second** between all HTTP calls — both search pages and detail pages.

```python
time.sleep(1)  # between search pages
time.sleep(1)  # between detail page fetches
```

Do not remove or reduce these sleeps. Craigslist will 403-block the IP if requests come in too fast. If you're hitting rate limits despite the 1-second delay, increase to 2 seconds.

The scraper uses a browser-like `User-Agent` header to reduce block likelihood:
```
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...
```

---

## Listing ID Generation

Each listing gets a stable `listing_id` = MD5 hash of the canonical URL (query params stripped, lowercased). This ensures the same listing scraped twice produces the same ID, enabling deduplication against the Sheets data.

```python
canonical = url.split("?")[0].lower().rstrip("/")
listing_id = hashlib.md5(canonical.encode("utf-8")).hexdigest()
```

---

## Data Merge Logic

JSON-LD data takes priority over detail page data. When merging:

```python
for key, value in detail.items():
    if key in partial and partial[key] is not None and partial[key] != "":
        continue  # keep the JSON-LD value
    partial[key] = value
```

This means coordinates and price from the structured data are never overwritten by the HTML scrape. The detail page fills in fields that JSON-LD doesn't have: description, address, bathrooms, sqft, neighborhood.

---

## Known Fragility Points and Fallbacks

| Risk | Symptom | Fallback |
|---|---|---|
| `ld_searchpage_results` tag missing | `[WARNING] JSON-LD tag not found` in logs | Returns empty list for that page; scraper continues with remaining pages |
| JSON-LD structure changed | Parse failure or unexpected nesting | Catch `KeyError`/`AttributeError`; log warning; skip that listing |
| Detail page 404 | Listing was deleted between search and detail fetch | Skip silently, move on |
| IP blocked | HTTP 403 on any request | Abort scrape for that page; pipeline saves error status |
| Address field empty | `.mapaddress` not found, `[data-address]` absent | `address_raw = ""`, `address_normalized = ""`, geocoding will fail gracefully |
| Price missing | Neither JSON-LD nor `.price` has a value | `price = None`; listing scores 0 on price; NOT auto-rejected |

---

## How to Check if Craigslist Structure Changed

Run the scraper in test mode (fetches only 5 listings):

```bash
python tools/scrape.py
```

Check the output:
- Should print `[INFO] Fetching search page 1 (start=0) ...`
- Should print 5 detail page fetches
- Should save `.tmp/craigslist_raw.json` with 5 listings

Then inspect the file:
```bash
cat .tmp/craigslist_raw.json | python -m json.tool | head -60
```

**Healthy output**: listings with non-null `title`, `url`, and at least some of `price`, `lat`, `lon`, `description_full`.

**Signs of structure change**:
- Listings have `title = "(no title)"` and empty descriptions
- `lat` / `lon` are null for all listings
- Zero listings returned despite the search URL working in a browser

If structure has changed, compare the live HTML source of the search page against the selectors above and update `scrape.py` accordingly.

---

## Error Patterns to Watch For

### HTTP 403 — Blocked

```
[WARNING] Failed to fetch search page (start=0): 403 Client Error: Forbidden
```

**Cause**: Too many requests, or Craigslist flagged the IP.
**Fix**: Wait 30–60 minutes. If persistent, try rotating the `User-Agent` string or running from a different network. Do not spam retries.

### JSON-LD Parse Failure — Structure Changed

```
[WARNING] JSON-LD tag not found on search page (start=0). Craigslist may have changed its markup.
```

Or:
```
[WARNING] Failed to parse JSON-LD on search page (start=0): ...
```

**Cause**: Craigslist updated their HTML structure.
**Fix**: Load the search URL in a browser, view source, find the `<script>` tag with listing data. Update the selector in `scrape_search_page()` to match the new tag ID or structure.

### All Listings Missing Descriptions

Every listing has `description_full = ""`.

**Cause**: The `#postingbody` selector no longer matches the description element.
**Fix**: Inspect a live listing detail page. Find the element containing the listing text and update the selector in `scrape_listing_detail()`.

### Zero Results Returned

Scraper runs but returns 0 listings. Could be:
1. The search URL is returning no results (check in browser — maybe SF inventory is thin right now)
2. JSON-LD is present but the `itemListElement` array is empty
3. All listings are duplicates of already-seen IDs (unlikely on first run)

---

## Raw Output File

```
.tmp/craigslist_raw.json
```

This file is saved at the end of the scrape step, before geocoding. If a later step fails, you can re-run geocode + score on this file without re-scraping. It contains the full listing schema for every scraped listing (with feature flags all at defaults — they're populated in the feature extraction step).

---

## Lessons Learned

*(Fill this section in as issues are discovered. Include the date, what broke, what fixed it, and any changes made to the scraper or workflow.)*
