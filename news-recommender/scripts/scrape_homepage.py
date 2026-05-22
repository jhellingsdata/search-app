#!/usr/bin/env python3
"""
ECO Homepage Staleness Scraper
==============================
Scrapes the Economics Observatory homepage, records the ordered list of
article titles and URLs, and computes a staleness score against the
previous day's snapshot.

Usage:
    uv run python scripts/scrape_homepage.py            # normal daily run
    uv run python scripts/scrape_homepage.py --dry-run  # print snapshot, don't save
    uv run python scripts/scrape_homepage.py --discover # dump all candidate links found
    uv run python scripts/scrape_homepage.py --dump-html  # save raw HTML to data/homepage_debug.html
    uv run python scripts/scrape_homepage.py --date 2025-01-15  # run as if it were that date
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://www.economicsobservatory.com"
SNAPSHOTS_DIR = Path(__file__).parent.parent / "data" / "snapshots"
DATA_DIR = Path(__file__).parent.parent / "data"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# CSS selectors tried individually — the one returning the most valid article
# links wins. Order still matters as a tiebreaker.
ARTICLE_SELECTORS = [
    # Semantic article tags (most reliable on modern WP themes)
    "article a[href]",
    # ECO uses `.card` and `.article-card` class patterns
    ".card a[href]",
    ".article-card a[href]",
    ".post-card a[href]",
    # Gutenberg block editor (WP 5+)
    ".wp-block-post a[href]",
    ".wp-block-query a[href]",
    # Heading-anchored links — ECO article titles are typically in h2/h3
    "h2 a[href]",
    "h3 a[href]",
    # Class substring matches — catch custom theme variations
    "[class*='article'] a[href]",
    "[class*='story'] a[href]",
    "[class*='post'] a[href]",
    "[class*='card'] a[href]",
    # Broad fallback: all links inside <main>
    "main a[href]",
]

# Non-article ECO paths to explicitly exclude
_ECO_NON_ARTICLE_PATHS = {
    "/", "/about", "/team", "/contact", "/subscribe",
    "/topics", "/events", "/charts", "/data", "/podcast",
    "/newsletter", "/partners", "/jobs", "/press",
    "/privacy-policy", "/terms", "/cookies",
}

_SKIP_PREFIXES = (
    "/tag/", "/category/", "/author/", "/search",
    "/page/", "/wp-", "/feed", "/sitemap",
    "/topic/", "/type/", "/series/",
)


def _is_article_url(href: str) -> bool:
    """Return True if the URL looks like an ECO article rather than nav/footer."""
    if not href:
        return False
    parsed = urlparse(href)
    # Must be on the ECO domain or a relative path
    if parsed.scheme and parsed.netloc and "economicsobservatory" not in parsed.netloc:
        return False
    path = parsed.path.rstrip("/")
    if not path:
        return False
    # Skip anchor-only or query-only links
    if path.startswith("#"):
        return False
    # Skip known non-article paths
    if path in _ECO_NON_ARTICLE_PATHS:
        return False
    # Skip known non-article path prefixes
    if any(path.startswith(p) for p in _SKIP_PREFIXES):
        return False
    # ECO article slugs are single-segment, hyphenated, typically > 10 chars
    # e.g. /do-tariffs-cause-inflation or /uk-economy-2025-outlook
    segments = [s for s in path.split("/") if s]
    if len(segments) != 1:
        return False
    slug = segments[0]
    # Must contain at least one hyphen (no plain short words like /faq)
    if "-" not in slug:
        return False
    return True


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_homepage() -> str:
    """Fetch the ECO homepage HTML. Raises on HTTP errors."""
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        resp = client.get(BASE_URL)
        resp.raise_for_status()
    return resp.text


def _normalise_url(href: str) -> str:
    """Resolve relative URL and strip fragment/query."""
    if href and not href.startswith("http"):
        href = urljoin(BASE_URL, href)
    return urlparse(href)._replace(fragment="", query="").geturl().rstrip("/")


def _get_title(a_tag) -> str:
    """Extract article title from a link tag and its immediate context."""
    # 1. Direct link text
    title = a_tag.get_text(" ", strip=True)
    if title:
        return " ".join(title.split())
    # 2. title attribute
    title = a_tag.get("title", "").strip()
    if title:
        return title
    # 3. Nearest heading ancestor
    parent = a_tag.find_parent(["h1", "h2", "h3", "h4"])
    if parent:
        title = parent.get_text(" ", strip=True)
        if title:
            return " ".join(title.split())
    # 4. aria-label
    title = a_tag.get("aria-label", "").strip()
    return title


def _collect_articles_for_selector(soup, selector: str) -> list[dict]:
    """Return deduplicated article dicts for a single CSS selector."""
    seen: set[str] = set()
    results: list[dict] = []
    for a_tag in soup.select(selector):
        href = a_tag.get("href", "").strip()
        url = _normalise_url(href)
        if not _is_article_url(href):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = _get_title(a_tag)
        if not title:
            continue
        results.append({"rank": len(results) + 1, "title": title, "url": url})
    return results


def extract_articles(html: str, discover: bool = False) -> list[dict]:
    """
    Parse the homepage HTML and return an ordered list of articles:
        [{"rank": 1, "title": "...", "url": "..."}, ...]

    Strategy: try every selector independently; pick the one that yields
    the most valid article links. This is more robust than a waterfall
    approach when the "best" selector appears later in the list.

    If `discover=True`, print a per-selector breakdown (useful when the
    site changes its markup).
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove nav, header, footer, sidebar noise before any selector work
    for tag in soup.select("nav, header, footer, [role='navigation'], aside, .sidebar"):
        tag.decompose()

    if discover:
        _print_discover_report(soup)

    best_articles: list[dict] = []
    best_selector: str = ""

    for selector in ARTICLE_SELECTORS:
        articles = _collect_articles_for_selector(soup, selector)
        if len(articles) > len(best_articles):
            best_articles = articles
            best_selector = selector
        # Once we have a confident match (10+ articles) stop searching
        if len(best_articles) >= 10:
            break

    if best_selector and not discover:
        print(f"  (winning selector: {best_selector!r} → {len(best_articles)} articles)")

    # Re-rank sequentially (in case selector order introduced gaps)
    for i, a in enumerate(best_articles, 1):
        a["rank"] = i

    return best_articles


def _print_discover_report(soup) -> None:
    """Print per-selector breakdown for debugging."""
    print("\n=== DISCOVER MODE — results per selector ===\n")
    for sel in ARTICLE_SELECTORS:
        articles = _collect_articles_for_selector(soup, sel)
        print(f"Selector: {sel!r}  → {len(articles)} articles")
        for a in articles[:8]:
            print(f"  [{a['rank']:>2}] {a['title'][:70]}")
            print(f"        {a['url']}")
        if len(articles) > 8:
            print(f"        … and {len(articles) - 8} more")
    print("\n=== END DISCOVER ===\n")


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------

def snapshot_path(for_date: date) -> Path:
    return SNAPSHOTS_DIR / f"{for_date.isoformat()}.json"


def save_snapshot(articles: list[dict], for_date: date) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(for_date)
    payload = {
        "date": for_date.isoformat(),
        "url": BASE_URL,
        "article_count": len(articles),
        "articles": articles,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_snapshot(for_date: date) -> dict | None:
    path = snapshot_path(for_date)
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Staleness scoring
# ---------------------------------------------------------------------------

def compute_staleness(today: list[dict], yesterday: list[dict]) -> dict:
    """
    Compare two ordered article lists and return staleness metrics.

    Metrics:
      - unchanged_fraction: share of slots where today's URL == yesterday's URL
        (0.0 = fully fresh, 1.0 = nothing changed)
      - unchanged_count / total_slots
      - per_slot: list of {rank, unchanged, today_url, yesterday_url}
    """
    max_slots = max(len(today), len(yesterday))
    today_by_rank = {a["rank"]: a for a in today}
    yest_by_rank = {a["rank"]: a for a in yesterday}

    per_slot = []
    unchanged = 0
    for rank in range(1, max_slots + 1):
        t = today_by_rank.get(rank)
        y = yest_by_rank.get(rank)
        if t is None or y is None:
            same = False
        else:
            same = t["url"] == y["url"]
        if same:
            unchanged += 1
        per_slot.append({
            "rank": rank,
            "unchanged": same,
            "today_title": t["title"] if t else None,
            "today_url": t["url"] if t else None,
            "yesterday_title": y["title"] if y else None,
            "yesterday_url": y["url"] if y else None,
        })

    return {
        "unchanged_count": unchanged,
        "total_slots": max_slots,
        "unchanged_fraction": round(unchanged / max_slots, 4) if max_slots else 0.0,
        "fully_stale": unchanged == max_slots,
        "per_slot": per_slot,
    }


def print_staleness_report(today_date: date, staleness: dict) -> None:
    pct = staleness["unchanged_fraction"] * 100
    status = "🔴 FULLY STALE" if staleness["fully_stale"] else (
        "🟡 PARTLY STALE" if pct >= 50 else "🟢 MOSTLY FRESH"
    )
    print(f"\n{'='*60}")
    print(f"  ECO Homepage Staleness Report — {today_date.isoformat()}")
    print(f"{'='*60}")
    print(f"  Status  : {status}")
    print(f"  Unchanged: {staleness['unchanged_count']} / {staleness['total_slots']} slots ({pct:.0f}%)")
    print(f"{'='*60}")
    print(f"  {'Rank':<5} {'Changed?':<10} {'Title (today)':<50}")
    print(f"  {'-'*65}")
    for slot in staleness["per_slot"]:
        changed_marker = "  —     " if slot["unchanged"] else "  ✓ NEW "
        title = (slot["today_title"] or slot["yesterday_title"] or "—")[:48]
        print(f"  {slot['rank']:<5} {changed_marker:<10} {title}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape the ECO homepage and compute a staleness score."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and parse the homepage but do NOT save the snapshot to disk.",
    )
    p.add_argument(
        "--discover",
        action="store_true",
        help="Print all candidate links found by each CSS selector (for debugging).",
    )
    p.add_argument(
        "--dump-html",
        action="store_true",
        help="Save raw fetched HTML to data/homepage_debug.html for inspection.",
    )
    p.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        metavar="YYYY-MM-DD",
        help="Treat this date as 'today' (useful for backfilling or testing).",
    )
    p.add_argument(
        "--compare-date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Compare against this date instead of yesterday (default: yesterday).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today_date: date = args.date
    compare_date: date = args.compare_date or (today_date - timedelta(days=1))

    print(f"Fetching {BASE_URL} ...")
    try:
        html = fetch_homepage()
    except httpx.HTTPStatusError as exc:
        print(f"ERROR: HTTP {exc.response.status_code} from {BASE_URL}", file=sys.stderr)
        return 1
    except httpx.RequestError as exc:
        print(f"ERROR: Network error — {exc}", file=sys.stderr)
        return 1

    print(f"Fetched {len(html):,} bytes of HTML.")

    if args.dump_html:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        debug_path = DATA_DIR / "homepage_debug.html"
        debug_path.write_text(html, encoding="utf-8")
        print(f"Raw HTML saved → {debug_path}")

    print(f"Parsing HTML ...")
    articles = extract_articles(html, discover=args.discover)

    if not articles:
        print(
            "WARNING: No articles found. Run with --discover to debug selector matches, "
            "or with --dump-html to inspect the raw HTML.",
            file=sys.stderr,
        )
        return 1

    print(f"\nFound {len(articles)} articles:")
    for a in articles:
        print(f"  [{a['rank']:>2}] {a['title'][:70]}")
        print(f"       {a['url']}")

    if args.dry_run:
        print("\n[dry-run] Snapshot NOT saved.")
    else:
        path = save_snapshot(articles, today_date)
        print(f"\nSnapshot saved → {path}")

    # Staleness comparison
    yesterday_snapshot = load_snapshot(compare_date)
    if yesterday_snapshot is None:
        print(
            f"\nNo snapshot found for {compare_date.isoformat()} — "
            "run again tomorrow for a staleness comparison."
        )
    else:
        staleness = compute_staleness(articles, yesterday_snapshot["articles"])
        print_staleness_report(today_date, staleness)

    return 0


if __name__ == "__main__":
    sys.exit(main())
