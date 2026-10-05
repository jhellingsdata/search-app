"""
Bring the search dataset in line with the Economics Observatory website.

Run from backend/:

    uv run update_articles.py --dry-run       # show what would change, change nothing
    uv run update_articles.py                 # sync dataset -> embed -> upload to Pinecone -> export frontend data
    uv run update_articles.py --article <url-or-slug>   # force a re-scrape of one article
    uv run update_articles.py --refresh-all   # re-scrape every article (e.g. after a scraper fix)
    uv run update_articles.py --skip-scrape   # only sync Pinecone with all_articles.json

Each run reads the full article list from the WordPress REST API, then:
  - adds new articles
  - follows permalink changes (matched by WordPress post ID), renaming the record and its Pinecone vector
  - re-scrapes articles edited on the site since they were last scraped
  - reports stored articles that are no longer published
Pinecone is the record of what has been embedded, so re-running after a failure is always safe.

See backend/UPDATING.md for the full guide.
"""
import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
ARTICLES_PATH = BACKEND_DIR / 'data' / 'all_articles.json'
FRONTEND_ARTICLES_PATH = REPO_ROOT / 'frontend' / 'src' / 'data' / 'articles.json'
FRONTEND_FIELDS = ('title', 'date', 'slug', 'url')
EMBEDDINGS_BACKUP_DIR = BACKEND_DIR / 'data' / 'embeddings'
LOG_DIR = BACKEND_DIR / 'logs'
SAVE_EVERY = 25
SCRAPE_WORKERS = 4  # concurrent page fetches; each page takes about a second to load

# The app modules use flat imports and paths relative to backend/, so mirror how the API runs
sys.path.insert(0, str(BACKEND_DIR / 'app'))
os.chdir(BACKEND_DIR)
load_dotenv(REPO_ROOT / '.env')

from article_processor import ArticleProcessor  # noqa: E402
from article_sync import SyncPlan, edit_link, merge_scrape, plan_sync, search_fields  # noqa: E402


def setup_logging():
    """Log to the console and to logs/update_YYYY-MM-DD.log. HTTP request lines from the API clients are hidden."""
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_DIR / f"update_{datetime.now():%Y-%m-%d}.log"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger('httpx').setLevel(logging.WARNING)


def print_plan(plan: SyncPlan, articles: dict):
    print(f"\n{len(plan.new)} new articles:")
    for post in sorted(plan.new, key=lambda p: p['date']):
        print(f"  {post['date']}  {post['url']}")
    print(f"\n{len(plan.moved)} permalinks changed on the site:")
    for key, post in plan.moved:
        print(f"  {articles[key]['url']}\n    -> {post['url']}")
    unscraped = [key for key, _ in plan.modified if not articles[key].get('wp_modified')]
    edited = [(key, post) for key, post in plan.modified if articles[key].get('wp_modified')]
    print(f"\n{len(edited)} articles edited on the site since they were scraped:")
    for key, post in sorted(edited, key=lambda kp: kp[1]['modified']):
        print(f"  edited {post['modified'][:10]}  {key}")
    if unscraped:
        print(f"\n{len(unscraped)} articles have no WordPress modified time recorded yet (scraped before it was "
              f"tracked) and will be re-scraped once")
    print(f"\n{len(plan.missing_on_site)} stored articles are no longer published:")
    for key in plan.missing_on_site:
        print(f"  {articles[key]['url']}")


def scrape_posts(processor: ArticleProcessor, scrape_list: list):
    """Yield (key, post, scraped article or the exception raised), fetching pages concurrently."""
    def fetch(item):
        key, post = item
        try:
            return key, post, json.loads(json.dumps(processor.scrape_article(post['url'])))
        except Exception as e:
            return key, post, e

    with ThreadPoolExecutor(SCRAPE_WORKERS) as pool:
        yield from pool.map(fetch, scrape_list)


def apply_plan(processor: ArticleProcessor, plan: SyncPlan) -> tuple[set, set, list]:
    """Scrape and store everything in the plan.

    Returns (slugs to re-embed, old slugs whose vectors should be deleted, fields kept for review).
    """
    articles = processor.articles
    to_embed, old_slugs, review = set(), set(), []

    for old_key, post in plan.moved:
        record = articles.pop(old_key)
        old_slugs.add(old_key)
        logging.info(f"Permalink changed: {old_key} -> {post['slug']}")
        if post['slug'] not in articles:  # if both versions were stored, keep the one under the new slug
            articles[post['slug']] = {**record, 'slug': post['slug'], 'url': post['url']}

    scrape_list = plan.to_scrape
    try:
        results = scrape_posts(processor, scrape_list)
        for count, (key, post, scraped) in enumerate(tqdm(results, total=len(scrape_list), desc="Scraping",
                                                          disable=not scrape_list), 1):
            if isinstance(scraped, Exception):
                # Stored record (and its old wp_modified) are left alone, so the next run retries
                logging.error(f"Failed to scrape {post['url']}: {scraped!r}")
                continue
            scraped.update(slug=key, url=post['url'], wp_id=post['wp_id'], wp_modified=post['modified'])
            stored = articles.get(key)
            record, kept = merge_scrape(stored, scraped)
            if kept:
                review.append((key, post['wp_id'], kept))
                logging.warning(f"{key}: fresh scrape lost {', '.join(kept)} - kept the stored values")
            if stored is None or search_fields(stored) != search_fields(record):
                to_embed.add(key)
            articles[key] = record
            if count % SAVE_EVERY == 0:
                processor._save_articles()
    finally:
        processor._save_articles()

    # Records matched without a scrape still need their WordPress post ID backfilled
    for key, post in plan.matched.items():
        if key in articles and not articles[key].get('wp_id'):
            articles[key]['wp_id'] = post['wp_id']
    processor._save_articles()
    return to_embed, old_slugs - set(articles), review


def sync_pinecone(articles: dict, force: set = frozenset(), remove: set = frozenset()) -> list[str]:
    """Embed and upload articles missing from Pinecone (plus `force`), then delete the `remove` vectors.

    Returns the uploaded slugs.
    """
    from embedding_processor import ArticleEmbeddingProcessor
    from pinecone_manager import PineconeManager

    pinecone_manager = PineconeManager()
    indexed_slugs = pinecone_manager.list_article_ids()
    logging.info(f"Pinecone index holds {len(indexed_slugs)} vectors; dataset holds {len(articles)} articles")

    to_embed = {slug: article for slug, article in articles.items() if slug not in indexed_slugs or slug in force}
    uploaded = []
    if to_embed:
        logging.info(f"Embedding {len(to_embed)} articles")
        embeddings_df = ArticleEmbeddingProcessor().process_articles(to_embed, force_reembed=True)
        if embeddings_df.empty:
            raise RuntimeError("No embeddings were generated - check the OpenAI errors above")
        failed = set(to_embed) - set(embeddings_df['slug'])
        if failed:
            logging.error(f"Failed to embed {len(failed)} articles (re-run to retry): {sorted(failed)}")

        # Keep a local copy so a failed upload can be retried without paying for embeddings again
        EMBEDDINGS_BACKUP_DIR.mkdir(exist_ok=True)
        backup_path = EMBEDDINGS_BACKUP_DIR / f"embeddings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
        embeddings_df.to_pickle(backup_path)
        logging.info(f"Saved embeddings backup to {backup_path.relative_to(REPO_ROOT)}")

        pinecone_manager.upsert_articles(embeddings_df, verbose=False)
        uploaded = list(embeddings_df['slug'])
        verify_upload(pinecone_manager, uploaded)
    else:
        logging.info("No vectors need uploading")

    # Delete vectors for old permalinks only once their replacement exists
    removable = sorted(slug for slug in remove & indexed_slugs if slug not in articles)
    if removable:
        pinecone_manager.index.delete(ids=removable)
        logging.info(f"Deleted {len(removable)} vectors for old permalinks: {removable}")

    orphans = indexed_slugs - set(articles) - set(removable)
    if orphans:
        logging.warning(f"{len(orphans)} vectors in Pinecone have no matching article: {sorted(orphans)}. "
                        f"See 'Articles no longer published' in UPDATING.md")
    return uploaded


def verify_upload(pinecone_manager, slugs: list[str], attempts: int = 6):
    """Check uploaded vectors can be fetched back (serverless indexes take a few seconds to catch up)."""
    for attempt in range(attempts):
        found = set()
        for i in range(0, len(slugs), 100):
            found |= set(pinecone_manager.index.fetch(ids=slugs[i:i + 100]).vectors)
        if found == set(slugs):
            logging.info(f"Verified all {len(slugs)} uploaded vectors are in Pinecone")
            return
        time.sleep(5)
    logging.warning(f"{len(set(slugs) - found)} uploaded vectors not yet visible in Pinecone: "
                    f"{sorted(set(slugs) - found)}. Re-run with --skip-scrape to check again.")


def export_frontend_data(articles: dict):
    """Write the slim title/date/slug/url copy of the dataset used by the frontend date chart."""
    frontend_articles = {slug: {field: article[field] for field in FRONTEND_FIELDS}
                         for slug, article in articles.items()}
    with open(FRONTEND_ARTICLES_PATH, 'w') as f:
        json.dump(frontend_articles, f)
    logging.info(f"Exported {len(frontend_articles)} articles to {FRONTEND_ARTICLES_PATH.relative_to(REPO_ROOT)}")


def upload_to_s3():
    """Upload all_articles.json to the S3 location the deployed API loads from (USE_S3=true)."""
    import boto3

    bucket, key = os.getenv('S3_BUCKET'), os.getenv('S3_ARTICLES_KEY')
    if not bucket or not key:
        raise RuntimeError("Set S3_BUCKET and S3_ARTICLES_KEY in .env to upload to S3")
    boto3.client('s3').upload_file(str(ARTICLES_PATH), bucket, key)
    logging.info(f"Uploaded {ARTICLES_PATH.name} to s3://{bucket}/{key}")


def resolve_article(identifier: str, plan: SyncPlan, wp_index: list[dict]) -> int:
    """Find the WordPress post ID for a URL or slug - either its current permalink or a stored (old) one."""
    target = identifier.rstrip('/').split('/')[-1].lower()
    for post in wp_index:
        if post['slug'].lower() == target:
            return post['wp_id']
    for key, post in plan.matched.items():
        if key.lower() == target:
            return post['wp_id']
    sys.exit(f"'{identifier}' is not a published article on the site, or in the dataset")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true',
                        help="Show what would change on this run, without scraping, embedding or writing anything")
    parser.add_argument('--article', metavar='URL_OR_SLUG', action='append',
                        help="Re-scrape (and re-embed if changed) only this article, even if WordPress shows no "
                             "edit. Accepts its current or old URL/slug. Repeatable")
    parser.add_argument('--refresh-all', action='store_true',
                        help="Re-scrape every article, e.g. after improving the scraper")
    parser.add_argument('--skip-scrape', action='store_true',
                        help="Don't check the website; just sync Pinecone and the frontend with all_articles.json")
    parser.add_argument('--upload-s3', action='store_true',
                        help="Also upload all_articles.json to S3_BUCKET/S3_ARTICLES_KEY for the deployed API")
    args = parser.parse_args()
    setup_logging()

    processor = ArticleProcessor(articles_path=str(ARTICLES_PATH))
    count_before = len(processor.articles)
    to_embed, old_slugs, review, missing_on_site = set(), set(), [], []

    if not args.skip_scrape:
        try:
            wp_index = processor.get_wordpress_index()
        except requests.RequestException as e:
            if args.dry_run or args.article or args.refresh_all:
                sys.exit(f"WordPress API unavailable: {e!r}")
            logging.error(f"WordPress API unavailable ({e!r}). Falling back to the /answers listing: new articles "
                          f"will be added, but permalink changes and edits won't be detected until the API is back")
            processor.update_articles(skip_existing=True)
        else:
            plan = plan_sync(processor.articles, wp_index, refresh_all=args.refresh_all)
            if args.article:
                wp_ids = {resolve_article(identifier, plan, wp_index) for identifier in args.article}
                plan = plan_sync(processor.articles, wp_index, force_wp_ids=wp_ids).restrict_to(wp_ids)
            if args.dry_run:
                print_plan(plan, processor.articles)
                return
            missing_on_site = plan.missing_on_site
            to_embed, old_slugs, review = apply_plan(processor, plan)

    uploaded = sync_pinecone(processor.articles, force=to_embed, remove=old_slugs)
    export_frontend_data(processor.articles)
    if args.upload_s3:
        upload_to_s3()

    print(f"\nDone. Dataset: {count_before} -> {len(processor.articles)} articles; "
          f"{len(uploaded)} embedded and uploaded to Pinecone; {len(old_slugs)} old permalinks replaced.")
    if review:
        print(f"\n{len(review)} articles kept stored values because the fresh scrape came back without them. "
              f"Check the page, fix it in WordPress if needed, then re-run with --article <slug>:")
        for key, wp_id, fields in review:
            print(f"  {key}: {', '.join(fields)}  {edit_link(wp_id)}")
    if missing_on_site:
        print(f"\n{len(missing_on_site)} stored articles are no longer published on the site "
              f"(see 'Articles no longer published' in UPDATING.md): {missing_on_site}")
    print("\nNext: `uv run inspect_pipeline.py audit`, review `git diff --stat`, then commit and push.")


if __name__ == '__main__':
    main()
