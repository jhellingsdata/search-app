# Updating the article dataset

How to keep the semantic search in line with the Economics Observatory website, and how to test or inspect each step of the pipeline. This replaces the old `article-embedding/` notebooks (`update_tool.ipynb`, `minimise_all_articles.ipynb`, `test_embedding.ipynb`, `test_api.ipynb`). The scripts are:

- [`update_articles.py`](update_articles.py) syncs the dataset, Pinecone and the frontend data with the site.
- [`inspect_pipeline.py`](inspect_pipeline.py) is read-only. Use it to test and inspect each step and to review data quality.

## How the data flows

```
WordPress REST API (/wp-json/wp/v2/question)   ← list of every published article: post ID, link, modified time
        │  1. match to stored records; scrape new, moved and edited articles   (app/article_sync.py,
        ▼                                                                       app/article_processor.py)
backend/data/all_articles.json          ← master dataset, committed to git
        │  2. embed new or changed articles   (app/embedding_processor.py, OpenAI text-embedding-3-small)
        ▼
Pinecone index "eco-articles"           ← what /search queries; live as soon as it's uploaded
        │  3. export title/date/slug/url
        ▼
frontend/src/data/articles.json         ← feeds the D3 date chart; goes live when Vercel redeploys
```

| Updated | Effect | Needs a deploy? |
|---|---|---|
| Pinecone | New and changed articles appear in search results | No, it's live straight away |
| `frontend/src/data/articles.json` | Date chart and result highlighting | Yes: push to `main` and Vercel redeploys |
| `backend/data/all_articles.json` | The master copy, plus the API's `/stats` and `/categories` | Only for the deployed API, via S3 (see step 6) |

### How articles are identified

- **Dataset key and Pinecone vector ID:** the article's slug, the last part of its live URL (`/{slug}`).
- **Stable identity:** each record stores `wp_id`, the WordPress post ID. This never changes, even when a permalink is edited.
- **Edit tracking:** each record stores `wp_modified`, WordPress's last-modified time when it was scraped.

On every run, `update_articles.py` fetches the full article list from the WordPress API (around 12 requests) and matches each post to a stored record. It matches by post ID first. Records scraped before IDs were tracked are matched by URL, and failing that by title and publication date. From the matches it works out:

| Situation | What the update does |
|---|---|
| Post not in the dataset | Scrapes and embeds it |
| Post's link differs from the stored URL (permalink edited) | Moves the record to the new slug, re-scrapes it, uploads a vector under the new slug, then deletes the old vector |
| Post modified since it was scraped (byline added, retitled, text edited…) | Re-scrapes it. Re-embeds only if anything stored in Pinecone changed |
| Stored article no longer published | Reports it; nothing is deleted (see [Articles no longer published](#articles-no-longer-published)) |

Article pages are scraped from the live HTML. The WordPress API's `content` field holds raw block markup and differs between classic-editor and block-editor posts, so it isn't used. The API's own `slug` field isn't used either, because it can differ from the live permalink (e.g. a `-2` suffix); the slug always comes from the link.

## One-time setup

1. Install [uv](https://docs.astral.sh/uv/) (`brew install uv`), then create the environment:

   ```bash
   cd backend
   uv sync          # creates backend/.venv with Python 3.13 and all dependencies
   ```

   Every command below runs from `backend/` with `uv run`. You don't need to activate the venv. For notebooks or VS Code, select `backend/.venv` as the interpreter (`ipykernel` is included).

2. Put these keys in the repo-root `.env` (see `.env.example`):

   ```
   OPENAI_API_KEY=...       # embeddings
   PINECONE_API_KEY=...     # the eco-articles index
   USE_S3=false             # keep false locally: the local API reads backend/data/all_articles.json
   S3_BUCKET=...            # for --upload-s3
   S3_ARTICLES_KEY=...      # for --upload-s3
   AWS_ACCESS_KEY_ID=...    # for --upload-s3 (or use `aws configure`)
   AWS_SECRET_ACCESS_KEY=...
   AWS_DEFAULT_REGION=eu-west-2
   ```

**Python version:** 3.13, both locally (`.python-version`, `pyproject.toml`) and in the API's Docker image (`Dockerfile`). Keep these in step when upgrading.

**Dependencies:** `pyproject.toml`/`uv.lock` define the local environment. The Docker image still installs from `requirements.txt`. If you add a runtime dependency, add it to both: `uv add <pkg>`, then add the same line to `requirements.txt`.

## Routine update

From `backend/`:

**1. Check the scraper still works:**

```bash
uv run inspect_pipeline.py check
```

This parses the first listing page and re-scrapes a spread of stored articles plus the newest one. It fails if any required field comes back empty. It warns if a field differs from the stored copy, which means either an editorial change or that the site's markup has drifted. If it fails, see [When the scraper breaks](#when-the-scraper-breaks) before going further.

**2. See what will change.** Read-only:

```bash
uv run update_articles.py --dry-run
```

This lists new articles, changed permalinks, articles edited on the site, and stored articles that are no longer published.

**3. Run the update:**

```bash
uv run update_articles.py
```

This scrapes and stores everything in the plan. The dataset is saved every 25 articles and whenever a run stops, so an interrupted run loses nothing.

It then embeds new and changed articles and uploads them to Pinecone. It deletes the vectors for old permalinks only once their replacements are uploaded. It also backs up the new embeddings to `data/embeddings/` and appends to `data/embedded_articles.csv`.

Finally, it regenerates `frontend/src/data/articles.json`.

The output goes to the console and to `logs/update_<date>.log`. At the end it lists anything that needs your attention:
- articles where the fresh scrape lost fields, so the stored values were kept (see [Scrape safeguards](#scrape-safeguards))
- articles that are no longer published

Embedding costs about 260 tokens per article, so even re-embedding the whole archive costs about $0.01.

**4. Check the result:**

```bash
uv run inspect_pipeline.py audit       # data-quality checks across the whole dataset
uv run inspect_pipeline.py pinecone    # index and dataset should both list the same articles
git diff --stat                        # expect all_articles.json, articles.json, embedded_articles.csv
```

**5. Commit and push** to redeploy the frontend:

```bash
git add data/all_articles.json data/embedded_articles.csv ../frontend/src/data/articles.json
git commit -m "Articles update - <month>"
git push
```

**6. Deployed API data.** The API runs on AWS Elastic Beanstalk from the `search-app` ECR image (eu-west-2). The image only contains `app/`, so the deployed API reads `all_articles.json` from S3 (`USE_S3=true`), once at startup. That file only feeds `/stats` and `/categories`; search doesn't depend on it. To refresh it:

```bash
uv run update_articles.py --skip-scrape --upload-s3
```

Then restart the Elastic Beanstalk environment (AWS console → Elastic Beanstalk → the search-app environment → Actions → Restart app server(s)). **The upload alone isn't enough:** the running API keeps serving the copy it loaded at startup until it restarts.

> **Pending (5 October 2026):** S3 was refreshed to 1,111 articles (the previous copy dated from February 2025), but the Elastic Beanstalk environment hasn't been restarted yet, so the deployed `/stats` and `/categories` still reflect the old data.

**7. Spot-check.** Search for one of the new articles:

```bash
uv run inspect_pipeline.py search "<a new article's title>" --top-k 3
```

Or search on the live site. Either way, the new article should be the top result.

## Reviewing and fixing article details

Fixes are made in WordPress. The next update picks them up automatically, because the edit changes the post's modified time.

1. **Find articles that need attention.**

   ```bash
   uv run inspect_pipeline.py audit                     # summary of every issue type
   uv run inspect_pipeline.py audit --issue author      # every article with that issue: title, live URL, WordPress edit link
   uv run inspect_pipeline.py audit --csv review.csv    # every issue for every article, as a spreadsheet
   ```

   `--issue` matches part of the issue name, e.g. `author`, `teaser`, `short text` or `permalink`. The audit covers:
   - missing fields (teaser, text, categories)
   - recent articles without a byline
   - very short texts
   - non-standard permalinks
   - duplicate titles
   - stray whitespace

   Pre-2022 articles without a byline are counted separately, because the early Q&A format had none.

   If an issue is correct as it stands, record it in `data/audit_exceptions.json` with the reason, and `audit` will stop reporting it (`--all` shows them again). Examples: an article with a corporate author credited only at the end of the text, or a promotional page with no author.

   ```json
   "modern-data-visualisation": {"issues": ["no author"], "reason": "Promotional page for the masterclasses"}
   ```

2. **Fix the article in WordPress,** using the edit link.

3. **Check how it now scrapes:**

   ```bash
   uv run inspect_pipeline.py article <slug>
   ```

   This compares every scraped field with the stored record.

4. **Run the update.**

   ```bash
   uv run update_articles.py --dry-run   # the fixed articles appear under "edited on the site"
   uv run update_articles.py
   ```

   To refresh one article immediately, even if WordPress shows no edit, use `uv run update_articles.py --article <slug>`. It accepts the current or old URL/slug and is repeatable.

## Fixing permalinks

Some of the oldest articles were published with non-standard permalinks:
- nested paths: `/question/{title}` or `/news/{title}`
- numeric: `/12453`
- mixed case: `/frontlineNHS`

`audit --issue permalink` lists them with edit links.

To fix one:

1. Change the permalink in WordPress, to `/{article-title}`.
2. If the old URL isn't already redirected (two old URLs found in October 2026 returned 404), add a redirect from the old URL to the new one in WordPress, so external links keep working.
3. Run `uv run update_articles.py --dry-run`. The article should be listed under "permalinks changed on the site".
4. Run `uv run update_articles.py`. This happens automatically on the next routine update anyway.

The update makes these changes:
- In `all_articles.json`, the record is moved to the new slug with the new URL. The WordPress post ID stays the same.
- In Pinecone, a vector is uploaded under the new slug, with the new URL in its metadata, and the old slug's vector is deleted.
- In the frontend data, the article is re-exported with its new URL.

**Don't edit Pinecone by hand.** The update treats Pinecone as derived from `all_articles.json`. A vector renamed by hand would be reported as an orphan, and the old slug would be re-uploaded. If a hand edit has already happened, run `uv run inspect_pipeline.py pinecone`. It lists vectors with no matching article and articles with no vector; the next update re-uploads the missing ones, and the orphans can then be deleted (below).

## Articles no longer published

If an article is unpublished or deleted in WordPress, the update reports it under "no longer published" but doesn't remove it. That covers the case where an article is temporarily unpublished. If it's gone for good, remove it from the dataset and the index:

```bash
uv run python -c "
import json, sys; sys.path.insert(0, 'app')
from pinecone_manager import PineconeManager
slug = '<slug>'
articles = json.load(open('data/all_articles.json')); articles.pop(slug)
json.dump(articles, open('data/all_articles.json', 'w'))
PineconeManager().delete_article(slug)"
uv run update_articles.py --skip-scrape    # re-export the frontend data
```

## Scrape safeguards

Older articles were written in WordPress's classic editor, and some records were fixed by hand after the original scrape, so a fresh scrape can come back worse than the stored record. When an existing article is re-scraped, `merge_scrape` in `app/article_sync.py` handles this. It keeps the stored value of any field the fresh scrape returns empty (title, category, authors, categories, related articles, charts, teaser, text). It also keeps the stored text if the new text is less than half its length.

Kept fields are logged and listed at the end of the run with edit links. To accept a deliberate removal (e.g. a byline removed on purpose), clear the field in `all_articles.json` and re-run with `--article <slug>`.

## Testing and inspecting the pipeline

### Offline tests

```bash
uv run pytest
```

The offline tests make no network calls. They cover:
- the date parser
- listing and article parsing, against snippets of the site's current markup (`tests/test_article_processor.py`)
- matching posts to records (new, moved, edited, unpublished, and pre-tracking records matched by title and date) and the merge safeguards (`tests/test_article_sync.py`)
- the embedding text, the frontend export, and Pinecone syncing, including permalink moves, with fake Pinecone and OpenAI clients (`tests/test_update_pipeline.py`)

When the site's markup changes, update the snippets to match the new markup alongside the parser fix.

### Inspecting live steps

`inspect_pipeline.py` never writes to the dataset, Pinecone or S3.

| Command | Step | What it shows |
|---|---|---|
| `check [--sample 5]` | Scrape | Pass/fail smoke test of listing and article scraping against the live site |
| `listing [--page N]` | Scrape | Every article on a listing page as parsed, marked new, stored, or changed since stored |
| `article <url-or-slug> [--full]` | Scrape | Every scraped field for one article, plus a field-by-field comparison with the stored record |
| `embed-text <url-or-slug> [--live] [--embed]` | Embed | The exact text sent to OpenAI. `--live` builds it from a fresh scrape. `--embed` makes the real call |
| `audit [--issue NAME] [--csv FILE]` | Dataset | Data-quality issues, with review lists and edit links |
| `pinecone [slug]` | Vector DB | Index vs dataset (missing and orphaned vectors). With a slug, that vector's metadata, with any fields that differ from the dataset marked |
| `search "<query>" [--top-k] [--category] [--from] [--to]` | Retrieval | Results straight from Pinecone with similarity scores, bypassing the API |
| `api [--url URL]` | API | Calls `/`, `/stats`, `/categories` and one `/search` on a running API (default `http://localhost:8000`; `/search` is limited to 100 calls a day) |

`uv run update_articles.py --dry-run` is the read-only view of the WordPress sync itself.

To run the API locally:

```bash
uv run uvicorn --app-dir app main:app --reload
```

Its docs are at http://localhost:8000/docs.

## Other tasks

**Re-scrape everything** (e.g. after improving the scraper): `uv run update_articles.py --refresh-all`. This takes 5–10 minutes, with pages fetched four at a time. The scrape safeguards still apply, and only articles whose search fields changed are re-embedded.

**A run failed partway through.** Re-run it:
- Articles that failed to scrape keep their old `wp_modified`, so they're retried.
- Anything missing from Pinecone is uploaded.
- To retry only the embed/upload step, use `--skip-scrape`.

**Snapshot the index before a big change**, and restore it if something goes wrong:

```bash
uv run inspect_pipeline.py pinecone --snapshot                        # every vector + metadata -> data/embeddings/pinecone_snapshot_<time>.pkl
uv run app/pinecone_manager.py data/embeddings/pinecone_snapshot_<time>.pkl   # upsert it back
```

A restore overwrites matching vectors but doesn't remove vectors added since. Delete those afterwards: `inspect_pipeline.py pinecone` lists them as orphans once `all_articles.json` is also restored from git.

**Re-upload saved embeddings without calling OpenAI:** `uv run app/pinecone_manager.py` uploads the newest `data/embeddings/embeddings_*.pkl`.

**The WordPress API is down.** The update falls back to the old `/answers` listing scrape. New articles are still added, but permalink changes and edits aren't detected until the API is back.

## When the scraper breaks

The scraper reads the site's HTML, so a redesign can break it. Typical symptoms are `AttributeError: 'NoneType' object has no attribute ...` or a date-parsing `ValueError`.

1. Run `uv run inspect_pipeline.py check` to see which step fails.
2. Save the page with `curl -s <article-url> > page.html` and compare it with the selectors in `app/article_processor.py`.
3. After fixing:
   - Update the snippets in `tests/test_article_processor.py` and run `uv run pytest`.
   - Run `check` again: re-scraped stored articles should come back with no `CHANGED` fields.

History (October 2026):
- The listing markup dropped a `class=""` wrapper, and article pages started putting the author name inside the date `<span>`. Both are handled by matching on `a.primary-category`, the titled article link, and a regex date parser.
- Data Hub pages have a "Data Hub." `<h1>` before the article title, so the title is read from `h1.article__title`.
- Email addresses in article text (e.g. booking contacts) aren't needed for search, so they're removed when scraping, including Cloudflare's `[email protected]` placeholders.

Before trusting a scraper change across the archive, re-scrape every stored article and compare the results with `all_articles.json`. Check the differences are improvements (fixed bylines, retitles), not regressions. The October 2026 comparison found the scraper handles the classic-editor articles without losing any fields.

## Known data quirks

- **Missing bylines.** About 200 articles from 2020–21 have no byline, which is expected for the early Q&A format; some list "experts" in the sidebar, which isn't scraped.
- **Renamed category.** "Crime & policing" was renamed "Crime, policing & justice" on the site. Older articles keep the old name, so `/categories` lists both. Re-scraping updates them if the article pages now show the new name.
- **Leftover headings.** About 30 articles keep a misspelt or unusually capitalised "find out more"/"experts" heading at the end of their text. The embedding uses only the first three paragraphs, so search isn't affected.
- **Timezone offset in date filters.** `date_timestamp` metadata is computed in UK local time, so for articles published in British Summer Time it is one hour off UTC midnight. A date filter starting exactly on such an article's publication date can leave it out. This was judged not worth fixing.

## Reference

| Path | Role | In git? |
|---|---|---|
| `update_articles.py` | Entry point for all updates | yes |
| `inspect_pipeline.py` | Read-only testing, inspection and data-quality review | yes |
| `tests/` | Offline pytest suite | yes |
| `app/article_sync.py` | Matching WordPress posts to records (post ID, URL, title + date) and scrape safeguards | yes |
| `app/article_processor.py` | WordPress API index, plus scraping and parsing of listing and article pages | yes |
| `app/embedding_processor.py` | Embedding text recipe (title ×2, teaser, first 3 paragraphs, categories) and OpenAI calls | yes |
| `app/pinecone_manager.py` | Pinecone index access: upsert, search, list, delete | yes |
| `app/article_updater.py` | Legacy single-article refresh, superseded by `--article` | yes |
| `data/all_articles.json` | Master dataset (each record includes `wp_id` and `wp_modified`) | yes |
| `data/embedded_articles.csv` | Log of every embedding call (date, model, tokens) | yes |
| `data/audit_exceptions.json` | Audit issues reviewed and accepted, with reasons | yes |
| `data/embeddings/*.pkl` | Embedding backups for re-uploading without OpenAI (also kept in OneDrive `article-embedding/data-processing/data/`), plus `pinecone_snapshot_*.pkl` full index snapshots | no |
| `logs/` | Update run logs | no |

If you change the embedding text recipe or the model, every vector has to be regenerated so that queries and documents stay comparable. To do that, run `--skip-scrape` after deleting the vectors (or switching to a new index). The `PineconeManager` dimension (1536) must match the model.
