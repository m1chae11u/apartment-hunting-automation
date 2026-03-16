# Zillow Scraping — SOP

## Overview

Zillow listings are scraped via the **Apify** platform using the `maxcopell/zillow-scraper` actor. This avoids dealing with Zillow's aggressive PerimeterX bot detection directly. The scraper lives in `tools/scrape_zillow.py`.

---

## How It Works

1. The script builds a Zillow search URL with a `searchQueryState` JSON parameter encoding our filters (1BR, $2,500–$3,500, SF map bounds)
2. It calls the Apify actor via the `apify-client` Python SDK
3. The actor runs on Apify's infrastructure (handles proxies, browser rendering, bot detection)
4. Results are fetched from the actor's dataset and normalized to our standard listing schema
5. Output saved to `.tmp/zillow_raw.json`

---

## Apify Configuration

| Setting | Value |
|---|---|
| Actor | `maxcopell/zillow-scraper` |
| Auth | `APIFY_API_TOKEN` in `.env` |
| Extraction method | `PAGINATION` |
| Cost | ~$0.01–0.05 per run (a few cents) |

The actor is called with:
```python
run_input = {
    "searchUrls": [{"url": search_url}],
    "extractionMethod": "PAGINATION",
}
```

---

## Search Parameters

The search is constrained by a `searchQueryState` JSON object embedded in the URL:

- **Map bounds**: Tight to the Caltrain corridor (~1mi around 4th & King and 22nd St stations)
  - West: -122.4150, East: -122.3750
  - South: 37.7430, North: 37.7900
  - Covers: SoMa, South Beach, Mission Bay, Dogpatch, Potrero Hill
- **Filters**: For rent, 1BR, $2,500–$3,500
- **Excluded**: For sale, new construction sales, coming soon, auction, foreclosure

The tight map bounds avoid scraping irrelevant neighborhoods that `process.py` would filter out anyway, saving Apify credits.

---

## Field Mapping

Zillow's Apify output uses various field names. The normalizer tries multiple keys for each field:

| Our Schema | Zillow Keys (tried in order) |
|---|---|
| `url` | `detailUrl`, `url`, `link` (prepend `https://www.zillow.com` if relative) |
| `price` | `unformattedPrice`, `hdpData.homeInfo.price`, `price` |
| `address` | `address`, then assembled from `addressStreet` + `addressCity` + `addressState` + `addressZipcode` |
| `bedrooms` | `beds`, `hdpData.homeInfo.bedrooms` |
| `bathrooms` | `baths`, `hdpData.homeInfo.bathrooms` |
| `sqft` | `area`, `hdpData.homeInfo.livingArea` (only if > 100) |
| `lat/lon` | `latLong.latitude/longitude`, `hdpData.homeInfo.latitude/longitude` |
| `neighborhood` | `hdpData.homeInfo.neighborhood`, `neighborhood` |

### Known Missing Fields

From testing (31 listings scraped):
- **Neighborhood**: Missing on all listings (Zillow doesn't return it in search results)
- **Price**: Missing on ~23% of listings (multi-unit buildings show ranges)
- **Bathrooms**: Missing on ~23%
- **Sqft**: Missing on ~39%

These are expected gaps. The pipeline handles nulls gracefully — `process.py` uses lat/lon for distance filtering, not neighborhood.

---

## Running Standalone

```bash
python tools/scrape_zillow.py
```

Output:
```
[INFO] Starting Zillow scrape: SF 1BR rentals $2500-$3500
[INFO] Actor: maxcopell/zillow-scraper
[INFO] Actor run finished with status: SUCCEEDED
[INFO] Got N raw items from Apify
[INFO] Normalized N listings from Zillow
[INFO] Saved N listings → .tmp/zillow_raw.json
```

---

## Error Recovery

### Actor fails or times out
- Check Apify dashboard at `https://console.apify.com` for run details
- The actor may hit Zillow rate limits — usually resolves on retry
- Pipeline continues without Zillow data (has `|| echo "[WARN]"` fallback in `run_pipeline.sh`)

### `APIFY_API_TOKEN` not set
- Script prints `[ERROR] APIFY_API_TOKEN not set in .env` and returns empty list
- Add the token to `.env`: `APIFY_API_TOKEN=apify_api_...`

### Actor returns 0 results
- Zillow may have changed their page structure
- Check if the actor has updates on Apify's marketplace
- Try running the search URL manually in a browser to verify listings exist

---

## Cost Management

- Each actor run costs a few cents of Apify credit
- With twice-daily runs, expect ~$1–3/month
- Monitor usage at `https://console.apify.com/billing`
- The free tier includes $5/month of platform credits

---

## Lessons Learned

- **2026-03-12**: Apartments.com Apify actor (`sovereigntaylor/apartments-scraper`) uses CheerioCrawler (HTTP-only), which gets 403-blocked by Apartments.com anti-bot. Even with residential proxies configured, the actor cannot bypass detection. Switched to Playwright-based scraping, but that also got IP-rate-limited after testing. Ultimately dropped Apartments.com automated scraping entirely. Zillow's Apify actor works because it uses a proper browser-based approach.
