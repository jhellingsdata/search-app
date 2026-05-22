# ECO News-to-Article Recommender

Automated system for the [Economics Observatory](https://www.economicsobservatory.com) that:

1. **Monitors homepage freshness** — tracks which articles are on the ECO homepage each day and scores how stale it is.
2. **Scrapes daily news** (Phase 2) — pulls headlines from BBC, FT, The Guardian etc. and embeds them.
3. **Recommends articles + emails a digest** (Phase 3) — surfaces the most relevant ECO back-catalogue articles based on today's news, and sends a morning briefing.

See [PROJECT_PLAN.md](./PROJECT_PLAN.md) for full architecture and roadmap.

---

## Prerequisites

- Python 3.11+
- [UV](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Setup

```bash
# Clone / open the project
cd eco-news-recommender

# Install dependencies (UV creates .venv automatically)
uv sync
```

---

## Phase 1 — Homepage Staleness Scraper

### Run it

```bash
# Normal daily run — scrapes homepage, saves snapshot, compares to yesterday
uv run python scripts/scrape_homepage.py

# Dry run — parses and prints results but doesn't save anything to disk
uv run python scripts/scrape_homepage.py --dry-run

# Discovery mode — dumps all candidate article links found by each CSS selector
# Useful if the site redesign breaks the scraper
uv run python scripts/scrape_homepage.py --discover

# Backfill / test with a specific date
uv run python scripts/scrape_homepage.py --date 2025-06-01

# Compare against a specific historical date instead of yesterday
uv run python scripts/scrape_homepage.py --compare-date 2025-05-20
```

### What it produces

Daily JSON snapshots in `data/snapshots/YYYY-MM-DD.json`:

```json
{
  "date": "2025-05-22",
  "url": "https://www.economicsobservatory.com",
  "article_count": 12,
  "articles": [
    {"rank": 1, "title": "Do tariffs cause inflation?", "url": "https://www.economicsobservatory.com/do-tariffs-cause-inflation"},
    {"rank": 2, "title": "UK productivity puzzle", "url": "https://www.economicsobservatory.com/uk-productivity-puzzle"},
    ...
  ]
}
```

And a staleness report printed to stdout:

```
============================================================
  ECO Homepage Staleness Report — 2025-05-22
============================================================
  Status  : 🟡 PARTLY STALE
  Unchanged: 8 / 12 slots (67%)
============================================================
  Rank  Changed?   Title (today)
  -----------------------------------------------------------------
  1       ✓ NEW    Do tariffs cause inflation?
  2       —        UK productivity puzzle
  ...
```

### Scheduling (local)

Run daily via cron:

```cron
# Run at 08:00 every day
0 8 * * * cd /path/to/eco-news-recommender && uv run python scripts/scrape_homepage.py >> logs/scrape.log 2>&1
```

### Debugging the scraper

If the site redesigns and articles stop being detected, run `--discover` mode:

```bash
uv run python scripts/scrape_homepage.py --discover
```

This prints every candidate link found by each CSS selector so you can identify which selector to update in `ARTICLE_SELECTORS` at the top of the script.

---

## Project Structure

```
eco-news-recommender/
├── pyproject.toml          # UV/Python project config + dependencies
├── .python-version         # Pins Python 3.11
├── PROJECT_PLAN.md         # Full system design doc
├── README.md               # This file
├── scripts/
│   ├── scrape_homepage.py  # Phase 1 — homepage monitor (implemented)
│   ├── scrape_news.py      # Phase 2 — RSS news scraper (planned)
│   └── send_digest.py      # Phase 3 — recommender + email (planned)
└── data/
    └── snapshots/          # Daily homepage snapshots (gitignored)
```

---

## Development

```bash
# Install with dev extras (adds pytest, ruff)
uv sync --extra dev

# Lint
uv run ruff check scripts/

# Format
uv run ruff format scripts/

# Run tests (once added)
uv run pytest
```
