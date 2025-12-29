# Deploy to Vercel (Python Serverless)

This folder is a **Vercel-ready** version of your scraper.

## What you get
- `/api/scrape.py` — Serverless endpoint
- `/src/college_lead_scraper.py` — Refactored scraper (no file writes, configurable limits)
- `vercel.json` — forces Python runtime

## Deploy steps
1. Push this folder to GitHub.
2. In Vercel: **New Project** → import the repo.
3. Framework preset: **Other** (no build needed).
4. Deploy.

## Test
### Health
`GET https://<your-vercel-domain>/api/scrape`

### Scrape
`POST https://<your-vercel-domain>/api/scrape`
Body (JSON):
```json
{
  "college_name": "AIIMS Delhi",
  "max_faculty_pages": 2,
  "max_faculty_per_page": 8,
  "include_linkedin": false,
  "polite_delay_s": 0.0,
  "request_timeout_s": 10
}
```

## Notes (important)
- Vercel functions have execution limits. Keep `include_linkedin=false` unless you **really** need it.
- This is best-effort scraping; some sites will need custom selectors.
