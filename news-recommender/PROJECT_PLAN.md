# ECO News-to-Article Recommender — Project Plan

Automated system for the [Economics Observatory](https://www.economicsobservatory.com) that monitors homepage freshness, scrapes daily news, and recommends existing ECO articles for reposting based on semantic similarity to today's headlines.

---

## Architecture Overview

```
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│   Phase 1           │     │   Phase 2             │     │   Phase 3           │
│   Homepage Monitor  │────▶│   News Scraper        │────▶│   Recommender       │
│   (staleness score) │     │   (RSS + embeddings)  │     │   + Email Digest    │
└─────────────────────┘     └──────────────────────┘     └─────────────────────┘
         │                            │                            │
         └────────────────────────────┴────────────────────────────┘
                                      │
                              ┌───────▼────────┐
                              │  AWS Lambda    │
                              │  S3 (snapshots,│
                              │   embeddings)  │
                              │  RDS (history) │
                              └────────────────┘
```

---

## Phase 1 — Homepage Staleness Monitor

**Goal:** Know, on any given day, how stale the ECO homepage is — i.e. how many articles haven't changed since yesterday (or the last N days).

### What it does

1. Scrapes `economicsobservatory.com` homepage daily.
2. Extracts the ordered list of article titles and URLs (position matters — slot 1 is the hero, slots 2–N are the grid).
3. Saves a dated JSON snapshot to `data/snapshots/YYYY-MM-DD.json`.
4. Compares today vs. yesterday to produce a **staleness report**:
   - `unchanged_fraction` — share of slots showing the same article as yesterday (0.0 = fully fresh, 1.0 = nothing changed).
   - `per_slot_staleness` — for each slot, how many consecutive days it has held the same article.
   - `days_since_any_change` — streak of days with no homepage change at all.

### Outputs

- `data/snapshots/YYYY-MM-DD.json` — daily snapshot (local dev).
- Eventually: write snapshots to S3 (`s3://eco-news-recommender/snapshots/`).
- Staleness report logged to stdout (and optionally to `data/staleness_log.csv`).

### Script

`scripts/scrape_homepage.py`

### Dependencies (Phase 1 only)

- `httpx` — HTTP client.
- `beautifulsoup4` + `lxml` — HTML parsing.

---

## Phase 2 — News Scraper & Daily News Profile

**Goal:** Every morning, build a semantic profile of what's in the news today.

### What it does

1. **RSS ingestion** — polls a configurable list of feeds (BBC News, FT, The Times, The Guardian Economics, etc.) via `feedparser`.
2. **Article extraction** — for each item, records: title, source, published date, URL, intro/summary text.
3. **Embedding** — embeds each article (title + intro) using either:
   - `sentence-transformers` (`all-MiniLM-L6-v2`) — free, runs locally / in Lambda.
   - `openai` (`text-embedding-3-small`) — higher quality, pay-per-use.
4. **Daily news profile** — saves a JSON file with articles + embeddings to `data/news/YYYY-MM-DD.json` (locally) or S3.

### RSS Feeds (initial list)

```python
RSS_FEEDS = {
    "bbc_business":    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "ft_economics":    "https://www.ft.com/rss/home/economics",
    "guardian_econ":   "https://www.theguardian.com/business/economics/rss",
    "times_business":  "https://www.thetimes.co.uk/topic/economics/rss",
    "ons_releases":    "https://www.ons.gov.uk/generator?format=rss",
}
```

### Script

`scripts/scrape_news.py`

### Dependencies (Phase 2 adds)

- `feedparser`
- `sentence-transformers` and/or `openai`
- `numpy`

---

## Phase 3 — Article Recommender + Email Digest

**Goal:** Each morning, compare today's news against the ECO back-catalogue and surface the 5–10 most relevant existing articles for the social/comms team to repost.

### What it does

1. **Back-catalogue embeddings** — one-time (then incremental) embedding of all ECO articles. Stored in S3 or RDS (pgvector on RDS Postgres).
2. **Similarity search** — cosine similarity between today's news embeddings and each back-catalogue article embedding. Aggregate per article (e.g. max or mean similarity against top-K news items).
3. **LLM summary** — calls OpenAI GPT-4o to write a 3–4 sentence "today's economic news summary" from the top RSS headlines. This becomes the email intro.
4. **Email digest** — sends a daily HTML email via AWS SES (or SMTP fallback) containing:
   - Today's news summary paragraph.
   - Top 5–10 recommended ECO articles with title, URL, similarity score, and a one-line "why this is relevant" blurb (LLM-generated).

### Email Template (`templates/digest.html.j2`)

Jinja2 template — clean, minimal, readable on mobile.

### Script

`scripts/send_digest.py`

### Dependencies (Phase 3 adds)

- `openai`
- `boto3` (SES + S3)
- `jinja2`
- `psycopg2-binary` (if using pgvector on RDS)

---

## Deployment

### Local Development

All phases run locally via UV:

```bash
uv sync                              # install all base deps
uv run python scripts/scrape_homepage.py
uv run python scripts/scrape_news.py
uv run python scripts/send_digest.py
```

Use a `.env` file for secrets (OpenAI key, AWS creds, email config).

### AWS Lambda

Each script becomes a separate Lambda handler:

| Lambda | Trigger | Purpose |
|--------|---------|---------|
| `homepage-monitor` | EventBridge (daily 08:00) | Phase 1 scrape + staleness score |
| `news-scraper` | EventBridge (daily 07:00) | Phase 2 RSS + embeddings |
| `digest-sender` | EventBridge (daily 09:00) | Phase 3 recommend + email |

**Packaging:** UV can build a Lambda-compatible zip. Use the `--no-dev` flag and bundle into a Lambda layer or container image.

```bash
uv export --no-dev --format requirements-txt > requirements.txt
pip install -r requirements.txt -t lambda_package/
```

### Storage

| Resource | Purpose |
|----------|---------|
| `s3://eco-news-recommender/snapshots/` | Daily homepage JSON snapshots |
| `s3://eco-news-recommender/news/` | Daily news + embeddings |
| `s3://eco-news-recommender/catalogue/` | Back-catalogue embeddings |
| RDS Postgres (pgvector) | Article metadata + vector similarity queries |

### Secrets

Store in AWS SSM Parameter Store or Secrets Manager:
- `OPENAI_API_KEY`
- `ECO_DB_URL` (RDS connection string)
- `SES_FROM_ADDRESS`, `DIGEST_TO_ADDRESSES`

---

## Milestones

| Phase | Status | Target |
|-------|--------|--------|
| Phase 1: Homepage monitor | 🟢 In progress | Week 1 |
| Phase 2: News scraper | ⬜ Planned | Week 2–3 |
| Phase 3: Recommender + digest | ⬜ Planned | Week 4–5 |
| Lambda deployment | ⬜ Planned | Week 6 |

---

## Open Questions

- **Embeddings model**: sentence-transformers (free, ~80MB Lambda layer) vs. OpenAI (pay-per-use, simpler). Start with OpenAI for speed; migrate to sentence-transformers if cost is an issue.
- **Back-catalogue source**: Does the ECO CMS have an API or sitemap for bulk article export? A sitemap crawl may be the easiest starting point.
- **pgvector vs. pure S3**: For <10K articles, cosine similarity on numpy arrays loaded from S3 may be fast enough without a database.
- **Email recipients**: Internal team digest only, or eventually subscriber-facing?
