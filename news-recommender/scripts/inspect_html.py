#!/usr/bin/env python3
"""
Quick HTML structure inspector for the ECO homepage.
Run once to help identify the right CSS selectors for the scraper.

Usage:
    uv run python scripts/inspect_html.py
"""

from __future__ import annotations
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.economicsobservatory.com"
DATA_DIR = Path(__file__).parent.parent / "data"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

def main():
    print(f"Fetching {BASE_URL} ...")
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        resp = client.get(BASE_URL)
        resp.raise_for_status()
    html = resp.text
    print(f"Got {len(html):,} bytes\n")

    # Save raw HTML so it can be inspected manually
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "homepage_debug.html"
    out.write_text(html, encoding="utf-8")
    print(f"Raw HTML saved → {out}\n")

    soup = BeautifulSoup(html, "lxml")

    # --- 1. Article / post / card tags ---
    print("=" * 60)
    print("1. <article> tags found:")
    articles = soup.find_all("article")
    print(f"   Count: {len(articles)}")
    for i, a in enumerate(articles[:5], 1):
        classes = " ".join(a.get("class", []))
        link = a.find("a", href=True)
        title_el = a.find(["h1","h2","h3","h4"])
        print(f"   [{i}] classes='{classes}'")
        print(f"        heading={title_el.get_text(strip=True)[:80] if title_el else 'none'}")
        print(f"        first link={link['href'][:80] if link else 'none'}")

    # --- 2. All unique class names containing card/post/article/story ---
    print("\n" + "=" * 60)
    print("2. Elements with class names containing: card, post, article, story, entry, item")
    keywords = ("card", "post", "article", "story", "entry", "item", "teaser", "news")
    class_counter: Counter = Counter()
    for tag in soup.find_all(True):
        for cls in tag.get("class", []):
            if any(k in cls.lower() for k in keywords):
                class_counter[f"<{tag.name}> .{cls}"] += 1
    for combo, count in class_counter.most_common(30):
        print(f"   {count:>4}x  {combo}")

    # --- 3. h2/h3 links on the page ---
    print("\n" + "=" * 60)
    print("3. h2/h3 tags containing links (first 15):")
    count = 0
    for tag in soup.find_all(["h2", "h3"]):
        link = tag.find("a", href=True)
        if not link:
            continue
        href = link["href"]
        if "economicsobservatory" in href or href.startswith("/"):
            text = tag.get_text(" ", strip=True)[:80]
            print(f"   <{tag.name}> [{href[:70]}]")
            print(f"            '{text}'")
            count += 1
            if count >= 15:
                break

    # --- 4. Links whose paths look like article slugs ---
    print("\n" + "=" * 60)
    print("4. Links with single-segment hyphenated paths (article slugs) — first 20:")
    seen = set()
    count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "economicsobservatory" not in href and not href.startswith("/"):
            continue
        path = urlparse(href).path.rstrip("/")
        segs = [s for s in path.split("/") if s]
        if len(segs) == 1 and "-" in segs[0] and href not in seen:
            seen.add(href)
            text = a.get_text(" ", strip=True)[:70]
            # Find the parent element's classes
            parent_classes = " ".join(a.parent.get("class", [])) if a.parent else ""
            print(f"   {href[:60]}")
            print(f"     text='{text}'  parent_cls='{parent_classes[:50]}'")
            count += 1
            if count >= 20:
                break

    print("\nDone. Share this output so selectors can be updated.")


if __name__ == "__main__":
    main()
