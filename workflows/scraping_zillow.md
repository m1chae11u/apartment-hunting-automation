# Zillow Scraping — SOP (Phase 2)

## Status

Not yet active. This is a Phase 2 source, added when Craigslist inventory feels thin or we want broader market coverage. Implement after Phase 1 is stable and running.

---

## Why Zillow Is Hard

Zillow runs **PerimeterX** bot detection, one of the more aggressive anti-scraping systems in use. Symptoms you'll hit without mitigation:

- HTTP 403 with a PerimeterX CAPTCHA page on the first request
- Successful first request, then a CAPTCHA wall on the second
- JavaScript-rendered blocking pages that return no listing data (just a challenge page)
- IP bans after a small number of requests in a short window

Unlike Craigslist, Zillow's defense is not just rate-limiting — it's active bot fingerprinting. Standard `requests` with a spoofed User-Agent will not work reliably. The page HTML also requires JavaScript execution to render listing data, so `requests` + `BeautifulSoup` alone is insufficient even without bot detection.

---

## Recommended Approach: ScraperAPI

[ScraperAPI](https://www.scraperapi.com) is a proxy service that handles bot detection, JavaScript rendering, and IP rotation on your behalf. You pass it a target URL and it returns the rendered HTML.

**Free tier**: 5,000 API credits/month. Each Zillow request costs 10 credits (JS rendering), so you get ~500 Zillow pages/month for free. That's plenty for twice-daily runs scraping a few pages at a time.

### Setup

1. Sign up at `https://www.scraperapi.com`
2. Get your API key from the dashboard
3. Add to `.env`:
   ```
   SCRAPER_API_KEY=your_key_here
   ```

### How It Works

ScraperAPI acts as a proxy. You pass your target URL as a query parameter to the ScraperAPI endpoint, along with your key and any options:

```python
import requests
import os

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")

def scrape_with_scraperapi(target_url: str) -> str:
    """Fetch target_url via ScraperAPI. Returns rendered HTML."""
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
        "render": "true",          # enable JavaScript rendering
        "country_code": "us",      # US IP address
        "premium": "true",         # use premium proxies (required for Zillow)
    }
    resp = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
    resp.raise_for_status()
    return resp.text
```

**Important**: Set `render=true` (JS rendering) and `premium=true` for Zillow. Without `premium`, you'll still hit bot detection even through ScraperAPI. Premium requests cost more credits — check the ScraperAPI pricing page for current rates.

Parse the returned HTML with BeautifulSoup exactly as you would with any other page. The response is the fully rendered DOM that a browser would see.

---

## Zillow URL Structure for SF 1BR Rentals

```
https://www.zillow.com/san-francisco-ca/rentals/?searchQueryState={"pagination":{},"isMapVisible":false,"mapBounds":{"west":-122.5155,"east":-122.3553,"south":37.7080,"north":37.8116},"filterState":{"fr":{"value":true},"fsba":{"value":false},"fsbo":{"value":false},"nc":{"value":false},"cmsn":{"value":false},"auc":{"value":false},"fore":{"value":false},"beds":{"min":1,"max":1},"price":{"min":2500,"max":3500},"mp":{"min":2500,"max":3500}},"isListVisible":true}
```

URL-encode the `searchQueryState` JSON before use. The map bounds are set to SF city limits roughly. Zillow paginates via `currentPage` inside the `searchQueryState` object.

Alternatively, start from the simpler base URL and let Zillow redirect to the full state URL:

```
https://www.zillow.com/san-francisco-ca/rentals/1-bedrooms/?price=2500-3500
```

**Inspect the actual URL** when navigating Zillow manually with your filters applied — copy that URL for the scraper. Zillow URL structures change over time.

---

## Zillow Listing Data Extraction

Zillow embeds listing data in a `<script id="__NEXT_DATA__" type="application/json">` tag. This is the most reliable extraction path — it contains structured JSON with all listing fields, much like Craigslist's JSON-LD.

```python
ld_tag = soup.find("script", {"id": "__NEXT_DATA__"})
data = json.loads(ld_tag.string)
# Navigate: data["props"]["pageProps"]["searchPageState"]["cat1"]["searchResults"]["listResults"]
```

The exact path within the JSON may change between Zillow deploys. If listings stop appearing, inspect `__NEXT_DATA__` in a browser's dev tools and re-map the path.

Fields to extract and map to the canonical schema:
- `zpid` → use as basis for `listing_id` (hash or use directly)
- `address` → `address_raw`
- `price` → strip `$`, `/mo`, commas
- `beds` → `bedrooms`
- `baths` → `bathrooms`
- `area` → `sqft`
- `latLong.latitude` / `latLong.longitude` → `lat`, `lon`
- `statusText`, `hdpData.homeInfo.description` → `description_full`
- `detailUrl` → prepend `https://www.zillow.com` → `url`

---

## Alternative: Playwright with Stealth

If ScraperAPI credits run out or the service is unavailable, Playwright with `playwright-stealth` is a fallback. It's more complex to set up and has a higher failure rate, but it's free.

```bash
pip install playwright playwright-stealth
playwright install chromium
```

```python
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    stealth_sync(page)
    page.goto("https://www.zillow.com/san-francisco-ca/rentals/...")
    html = page.content()
    browser.close()
```

**Known issues with Playwright approach**:
- Zillow detects headless Chromium even with stealth patches — success rate is ~60–70%
- CAPTCHA challenges may appear that pause the scrape
- Slower than ScraperAPI (full browser launch per session)
- Not suitable for high-frequency automated runs

Use ScraperAPI as the primary approach. Fall back to Playwright only for manual one-off fetches.

---

## Rate Limiting

Zillow is more sensitive than Craigslist. Recommended delays:
- **3–5 seconds** between requests (even through ScraperAPI)
- Maximum 50–100 listing pages per run to stay under ScraperAPI's credit budget
- If you see a spike in failed requests, stop and wait several hours before retrying

---

## Integration into Pipeline

When ready to activate:

1. Create `tools/scrape_zillow.py` following the same structure as `scrape_craigslist.py`:
   - Returns a list of dicts matching the canonical `_empty_listing()` schema
   - Implements `scrape_zillow(max_listings: int) -> list[dict]`
   - Saves raw output to `.tmp/zillow_raw.json`

2. In `tools/pipeline.py`, add Zillow to the scrape step:
   ```python
   if "zillow" in sources:
       raw_zillow = scrape_zillow(max_listings)
       all_listings.extend(raw_zillow)
   ```

3. Update the n8n HTTP call if sources need to be passed as a parameter, or hardcode `sources=["craigslist", "zillow"]` in `run_pipeline()`.

4. Test with `python tools/scrape_zillow.py` before wiring into the pipeline.

---

## Lessons Learned

*(Fill this section in as issues are discovered. Include the date, what broke, what fixed it, and any changes made to the scraper, ScraperAPI config, or this workflow.)*
