"""
Inspect and test each step of the article pipeline without changing any data.

    uv run inspect_pipeline.py check                 # live smoke test of the scraper - run before an update
    uv run inspect_pipeline.py listing [--page 2]    # how a listing page parses; new vs stored articles
    uv run inspect_pipeline.py article <url-or-slug> # every scraped field, compared with the stored record
    uv run inspect_pipeline.py embed-text <url-or-slug> [--live] [--embed]   # the exact text sent to OpenAI
    uv run inspect_pipeline.py audit [--issue author] [--csv review.csv]   # data-quality checks + review lists
    uv run inspect_pipeline.py pinecone [slug]       # index vs dataset; one vector's metadata vs the dataset
    uv run inspect_pipeline.py pinecone --snapshot   # save a full copy of the index to data/embeddings/
    uv run inspect_pipeline.py search "<query>"      # query Pinecone directly, bypassing the API
    uv run inspect_pipeline.py api [--url URL]       # exercise the running FastAPI endpoints

Run from backend/. Nothing here writes to all_articles.json, Pinecone or S3.
"""
import argparse
import collections
import csv
import json
import logging
import os
import sys
import textwrap
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ARTICLES_PATH = BACKEND_DIR / 'data' / 'all_articles.json'
# Issues reviewed and accepted, so audit stops reporting them: {slug: {"issues": [...], "reason": "..."}}
AUDIT_EXCEPTIONS_PATH = BACKEND_DIR / 'data' / 'audit_exceptions.json'
BASE_URL = 'https://www.economicsobservatory.com'

sys.path.insert(0, str(BACKEND_DIR / 'app'))
os.chdir(BACKEND_DIR)
load_dotenv(BACKEND_DIR.parent / '.env')
logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')

from article_processor import ArticleProcessor  # noqa: E402
from article_sync import edit_link, permalink_problem  # noqa: E402
from embedding_processor import prepare_text_for_embedding  # noqa: E402

# Fields every scraped article must have. author is excluded: early (2020-21) articles have no byline.
REQUIRED_FIELDS = ('title', 'date', 'slug', 'url', 'main_category', 'secondary_categories', 'teaser', 'text')
# Fields compared between a fresh scrape and the stored record
COMPARE_FIELDS = ('title', 'date', 'url', 'main_category', 'author', 'secondary_categories', 'teaser')
AUTHOR_EXPECTED_FROM = '2022-01-01'


def load_processor() -> ArticleProcessor:
    logging.getLogger().setLevel(logging.WARNING)
    return ArticleProcessor(articles_path=str(ARTICLES_PATH))


def to_url(identifier: str) -> str:
    return identifier if '/' in identifier else f"{BASE_URL}/{identifier}"


def scrape(processor: ArticleProcessor, identifier: str) -> dict:
    """Scrape one article, normalised to the same JSON shape as all_articles.json (tuples become lists)."""
    return json.loads(json.dumps(processor.scrape_article(to_url(identifier))))


def normalise(value):
    """Ignore whitespace differences (including inside lists) when comparing fields."""
    if isinstance(value, str):
        return ' '.join(value.split())
    if isinstance(value, list):
        return [normalise(item) for item in value]
    return value


def field_problems(article: dict) -> list[str]:
    problems = [f"missing {field}" for field in REQUIRED_FIELDS if not article.get(field)]
    if not article.get('author') and article.get('date', '') >= AUTHOR_EXPECTED_FROM:
        problems.append("no author (expected for articles since 2022)")
    if article.get('date', '') > date.today().isoformat():
        problems.append(f"date in the future: {article['date']}")
    if article.get('text') and len(article['text']) < 1000:
        problems.append(f"very short text ({len(article['text'])} chars)")
    return problems


def short(value, width: int = 100) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return textwrap.shorten(text.replace('\n', ' '), width=width, placeholder=' …')


# --- Commands -------------------------------------------------------------------------------------

def cmd_listing(args):
    processor = load_processor()
    print(f"Site has {processor.get_page_count()} listing pages. Page {args.page}:\n")
    for info in processor.get_articles_on_page(args.page):
        stored = processor.articles.get(info.slug)
        if not stored:
            status = 'NEW'
        else:
            changed = [f for f in ('title', 'date', 'url', 'main_category') if getattr(info, f) != stored[f]]
            status = f"changed: {', '.join(changed)}" if changed else 'stored'
        print(f"  {info.date}  {info.main_category:<34.34} {info.slug:<70.70}  [{status}]")


def cmd_article(args):
    processor = load_processor()
    article = scrape(processor, args.identifier)
    stored = processor.articles.get(article['slug'])

    print(f"Scraped {article['url']}\n")
    for field, value in article.items():
        if field == 'text' and not args.full:
            paragraphs = value.split('\n')
            print(f"  {'text':<21} {len(value)} chars, {len(paragraphs)} paragraphs")
            for paragraph in paragraphs[:3]:
                print(f"  {'':<21} │ {short(paragraph, 110)}")
        elif isinstance(value, list):
            print(f"  {field:<21} ({len(value)})")
            for item in value:
                print(f"  {'':<21} - {short(item, 110)}")
        else:
            print(f"  {field:<21} {value if args.full else short(value, 110)}")

    problems = field_problems(article)
    print(f"\nChecks: {'; '.join(problems) if problems else 'all required fields present'}")
    if stored is None:
        print("Not in all_articles.json yet.")
        return
    differences = [f for f in article if normalise(article[f]) != normalise(stored.get(f))]
    print(f"Compared with stored record: {'identical' if not differences else 'differs in ' + ', '.join(differences)}")
    for field in differences:
        if field == 'text':
            print(f"  text: stored {len(stored['text'])} chars -> now {len(article['text'])} chars")
        else:
            print(f"  {field}:\n    stored: {short(stored.get(field), 110)}\n    now:    {short(article[field], 110)}")


def cmd_embed_text(args):
    processor = load_processor()
    slug = args.identifier.rstrip('/').split('/')[-1]
    if args.live or slug not in processor.articles:
        source, article = 'freshly scraped page', scrape(processor, args.identifier)
    else:
        source, article = 'stored record', processor.articles[slug]

    text = prepare_text_for_embedding(article)
    print(f"Embedding input for '{article['slug']}' (from {source}):\n")
    print(textwrap.fill(text, width=110, initial_indent='  ', subsequent_indent='  '))
    print(f"\n{len(text)} characters, roughly {len(text) // 4} tokens")

    if args.embed:
        from embedding_processor import ArticleEmbeddingProcessor
        embedder = ArticleEmbeddingProcessor()
        vector, tokens = embedder._get_embedding(text)
        print(f"OpenAI {embedder.embedding_model}: {tokens} tokens, {len(vector)}-dimension vector, "
              f"first values {[round(v, 4) for v in vector[:4]]}")


def audit_issues(articles: dict) -> dict:
    """Map each issue name to the keys of the articles that have it."""
    issues = collections.defaultdict(list)
    for key, article in articles.items():
        for problem in field_problems(article):
            issues[problem.split(' (')[0].split(':')[0]].append(key)
        if key != article.get('slug') or article.get('url', '').rstrip('/').split('/')[-1] != key:
            issues['slug/url mismatch'].append(key)
        if article.get('main_category') not in article.get('secondary_categories', []):
            issues['main category not in secondary categories'].append(key)
        try:
            datetime.strptime(article.get('date', ''), '%Y-%m-%d')
        except ValueError:
            issues['unparseable date'].append(key)
        if article.get('title', '') != article.get('title', '').strip():
            issues['title has surrounding whitespace'].append(key)
        if problem := permalink_problem(article.get('url', '')):
            issues[f"non-standard permalink ({problem})"].append(key)
        if not article.get('wp_id'):
            issues['no WordPress post ID (run update_articles.py)'].append(key)

    titles = collections.Counter(a['title'].strip() for a in articles.values())
    issues['duplicate title'] = [k for k, a in articles.items() if titles[a['title'].strip()] > 1]
    return {issue: sorted(keys) for issue, keys in issues.items() if keys}


def cmd_audit(args):
    articles = json.loads(ARTICLES_PATH.read_text())
    issues = audit_issues(articles)
    exceptions = json.loads(AUDIT_EXCEPTIONS_PATH.read_text()) if AUDIT_EXCEPTIONS_PATH.exists() else {}
    accepted = [(issue, key, exceptions[key]['reason']) for issue, keys in issues.items() for key in keys
                if issue in exceptions.get(key, {}).get('issues', [])]
    if not args.all:
        hidden = {(issue, key) for issue, key, _ in accepted}
        issues = {issue: kept for issue, keys in issues.items()
                  if (kept := [key for key in keys if (issue, key) not in hidden])}

    if args.csv:
        with open(args.csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['issue', 'slug', 'title', 'date', 'main_category', 'url', 'edit_link'])
            for issue, keys in issues.items():
                for key in keys:
                    a = articles[key]
                    writer.writerow([issue, key, a['title'].strip(), a['date'], a['main_category'], a['url'],
                                     edit_link(a.get('wp_id'))])
        print(f"Wrote {sum(map(len, issues.values()))} rows to {args.csv}")
        return

    if args.issue:
        selected = {issue: keys for issue, keys in issues.items() if args.issue.lower() in issue.lower()}
        if not selected:
            sys.exit(f"No issue matches '{args.issue}'. Issues found: {', '.join(issues)}")
        for issue, keys in selected.items():
            print(f"{issue} ({len(keys)}):\n")
            for key in sorted(keys, key=lambda k: articles[k]['date'], reverse=True):
                a = articles[key]
                print(f"  {a['date']}  {a['title'].strip()}\n              {a['url']}")
                if a.get('wp_id'):
                    print(f"              {edit_link(a['wp_id'])}")
            print()
        return

    print(f"Auditing {len(articles)} articles in {ARTICLES_PATH.relative_to(BACKEND_DIR.parent)}\n")
    for issue, keys in sorted(issues.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(keys):>4}  {issue}: {', '.join(keys[:args.examples])}"
              f"{' …' if len(keys) > args.examples else ''}")
    if not issues:
        print("  No issues found")
    else:
        print("\n  List every article with an issue (with edit links): audit --issue \"<part of issue name>\"")
    if accepted and not args.all:
        print(f"  {len(accepted)} accepted exceptions hidden (data/audit_exceptions.json); show them with --all")
    elif accepted:
        print("\n  Accepted exceptions (data/audit_exceptions.json):")
        for issue, key, reason in accepted:
            print(f"    {key} [{issue}]: {reason}")

    dates = sorted(a['date'] for a in articles.values())
    no_author_early = sum(1 for a in articles.values() if not a['author'] and a['date'] < AUTHOR_EXPECTED_FROM)
    print(f"\n  Date range {dates[0]} to {dates[-1]}; "
          f"{no_author_early} pre-2022 articles have no byline (expected for the early format)")
    print(f"  Articles per year: {dict(sorted(collections.Counter(d[:4] for d in dates).items()))}")
    print(f"  Main categories ({len(set(a['main_category'] for a in articles.values()))}): "
          + ', '.join(f"{c} {n}" for c, n in collections.Counter(
              a['main_category'] for a in articles.values()).most_common()))


def cmd_check(args):
    """Live smoke test: does the scraper still read the site correctly?"""
    processor = load_processor()
    failures, warnings = [], []

    print("1. Listing page parsing")
    try:
        listed = processor.get_articles_on_page(1)
        incomplete = [a.slug for a in listed if not all([a.slug, a.title, a.date, a.url, a.main_category])]
        print(f"   parsed {len(listed)} articles from page 1; {len(incomplete)} incomplete")
        if not listed or incomplete:
            failures.append(f"listing page: {len(listed)} parsed, incomplete: {incomplete}")
    except Exception as e:
        listed = []
        failures.append(f"listing page failed to parse: {e!r}")
        print(f"   FAILED: {e!r}")

    # Stored articles spread evenly across the archive, plus the newest article on the site
    stored = sorted(processor.articles.values(), key=lambda a: a['date'])
    step = max(1, len(stored) // args.sample)
    targets = [a['slug'] for a in stored[::step][:args.sample]]
    if listed:
        targets.append(listed[0].slug)

    print(f"\n2. Article page scraping ({len(targets)} articles)")
    for slug in targets:
        try:
            article = scrape(processor, slug)
        except Exception as e:
            failures.append(f"{slug}: scrape failed: {e!r}")
            print(f"   FAILED   {slug}: {e!r}")
            continue
        problems = field_problems(article)
        record = processor.articles.get(slug)
        changed = [f for f in COMPARE_FIELDS if record and normalise(article[f]) != normalise(record.get(f))]
        if problems:
            failures.append(f"{slug}: {'; '.join(problems)}")
        if changed:
            warnings.append(f"{slug}: differs from stored record in {', '.join(changed)}")
        label = 'FAILED' if problems else ('CHANGED' if changed else 'ok')
        detail = '; '.join(problems) or (f"differs in {', '.join(changed)}" if changed else
                                         f"{len(article['text'])} chars, {len(article['author'])} authors, "
                                         f"{len(article['charts'])} charts")
        print(f"   {label:<8} {article['date']}  {slug[:60]:<60}  {detail}")

    print(f"\nResult: {len(failures)} failures, {len(warnings)} warnings")
    for message in failures:
        print(f"  FAIL  {message}")
    for message in warnings:
        print(f"  WARN  {message}  (an editorial change, or a sign the selectors have drifted)")
    if failures:
        sys.exit(1)


def cmd_pinecone(args):
    from pinecone_manager import PineconeManager
    manager = PineconeManager()
    articles = json.loads(ARTICLES_PATH.read_text())

    if args.snapshot:
        import pandas as pd
        ids, rows = sorted(manager.list_article_ids()), []
        for i in range(0, len(ids), 100):
            for vector_id, vector in manager.index.fetch(ids=ids[i:i + 100]).vectors.items():
                rows.append({'slug': vector_id, 'embedding': list(vector.values), **vector.metadata})
        path = BACKEND_DIR / 'data' / 'embeddings' / f"pinecone_snapshot_{datetime.now():%Y%m%d_%H%M%S}.pkl"
        path.parent.mkdir(exist_ok=True)
        pd.DataFrame(rows).to_pickle(path)
        print(f"Saved {len(rows)} vectors to {path.relative_to(BACKEND_DIR)}. "
              f"Restore with: uv run app/pinecone_manager.py {path.relative_to(BACKEND_DIR)}")
        return

    if args.slug:
        vectors = manager.index.fetch(ids=[args.slug]).vectors
        if args.slug not in vectors:
            print(f"'{args.slug}' is not in the index")
            return
        metadata, stored = vectors[args.slug].metadata, articles.get(args.slug, {})
        print(f"Metadata for '{args.slug}' ({len(vectors[args.slug].values)}-dim vector):\n")
        for field, value in sorted(metadata.items()):
            expected = stored.get(field)
            if field == 'charts':
                expected = [chart[0] for chart in stored.get('charts', [])]
            flag = '' if expected is None or normalise(expected) == normalise(value) else '   <- differs from dataset'
            print(f"  {field:<21} {short(value, 90)}{flag}")
        return

    stats = manager.get_index_stats()
    indexed = manager.list_article_ids()
    missing, orphans = set(articles) - indexed, indexed - set(articles)
    print(f"Index '{manager.index_name}': {stats.total_vector_count} vectors, {stats.dimension} dimensions")
    print(f"Dataset: {len(articles)} articles")
    print(f"In dataset but not in Pinecone ({len(missing)}): {sorted(missing) or '-'}")
    print(f"In Pinecone but not in dataset ({len(orphans)}): {sorted(orphans) or '-'}")


def cmd_search(args):
    from embedding_processor import ArticleEmbeddingProcessor
    from pinecone_manager import PineconeManager
    vector, tokens = ArticleEmbeddingProcessor()._get_embedding(args.query)
    results = PineconeManager().search(vector, top_k=args.top_k, filter_category=args.category,
                                       date_from=args.date_from, date_to=args.date_to)
    print(f"Top {args.top_k} for '{args.query}':\n")
    for match in results['matches']:
        meta = match['metadata']
        print(f"  {match['score']:.3f}  {meta['date']}  {meta['main_category'][:24]:<24}  {meta['title']}")


def cmd_api(args):
    import requests
    base = args.url.rstrip('/')
    checks = [
        ('GET', '/', None),
        ('GET', '/stats', None),
        ('GET', '/categories', None),
        ('POST', '/search', {'query': 'How does inflation affect the economy?', 'top_k': 3,
                             'date_from': '2024-01-01'}),
    ]
    for method, path, body in checks:
        try:
            response = requests.request(method, base + path, json=body, timeout=30)
            data = response.json()
            if path == '/search' and response.ok:
                data = [f"{r['date']} {r['title']}" for r in data['results']]
            print(f"{method} {path} -> {response.status_code}\n  {short(data, 300)}")
        except Exception as e:
            print(f"{method} {path} -> FAILED: {e!r}")
    print("\nNote: /search is rate limited to 100 requests/day per IP.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)

    check = commands.add_parser('check', help="Live smoke test of listing and article scraping")
    check.add_argument('--sample', type=int, default=5, help="Stored articles to re-scrape (default 5)")
    check.set_defaults(func=cmd_check)

    listing = commands.add_parser('listing', help="Show how a listing page parses")
    listing.add_argument('--page', type=int, default=1)
    listing.set_defaults(func=cmd_listing)

    article = commands.add_parser('article', help="Scrape one article and show every field")
    article.add_argument('identifier', metavar='URL_OR_SLUG')
    article.add_argument('--full', action='store_true', help="Print full text and untruncated fields")
    article.set_defaults(func=cmd_article)

    embed_text = commands.add_parser('embed-text', help="Show the exact text that gets embedded")
    embed_text.add_argument('identifier', metavar='URL_OR_SLUG')
    embed_text.add_argument('--live', action='store_true', help="Use a fresh scrape, not the stored record")
    embed_text.add_argument('--embed', action='store_true', help="Also call OpenAI (costs a fraction of a cent)")
    embed_text.set_defaults(func=cmd_embed_text)

    audit = commands.add_parser('audit', help="Data-quality checks across all_articles.json")
    audit.add_argument('--examples', type=int, default=5, help="Example slugs to show per issue")
    audit.add_argument('--issue', help="List every article with this issue (part of its name), with edit links")
    audit.add_argument('--csv', metavar='FILE', help="Write every issue to a CSV for review")
    audit.add_argument('--all', action='store_true', help="Include issues accepted in data/audit_exceptions.json")
    audit.set_defaults(func=cmd_audit)

    pinecone = commands.add_parser('pinecone', help="Compare the Pinecone index with the dataset")
    pinecone.add_argument('slug', nargs='?', help="Show this article's stored vector metadata")
    pinecone.add_argument('--snapshot', action='store_true',
                          help="Save every vector and its metadata to data/embeddings/ (a local file only)")
    pinecone.set_defaults(func=cmd_pinecone)

    search = commands.add_parser('search', help="Query Pinecone directly")
    search.add_argument('query')
    search.add_argument('--top-k', type=int, default=10)
    search.add_argument('--category')
    search.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD')
    search.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD')
    search.set_defaults(func=cmd_search)

    api = commands.add_parser('api', help="Exercise the running API's endpoints")
    api.add_argument('--url', default=os.getenv('API_URL', 'http://localhost:8000'))
    api.set_defaults(func=cmd_api)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
