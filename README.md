# Economics Observatory search

Semantic search over every Economics Observatory (ECO) article, so the team can find pieces on a topic to cite or re-post. The Newsdesk, now in development, will track the ECO homepage and email a daily digest recommending ECO articles to re-post alongside the day's economics news.

## What's here

| Folder | What it does | Runs on |
|---|---|---|
| `backend/` | The search API, and the pipeline that scrapes, embeds and uploads new articles | AWS Elastic Beanstalk, Pinecone |
| `frontend/` | The search website | Vercel |
| `newsdesk/` | Homepage tracker and daily digest (in development: see [`docs/plans/`](docs/plans/)) | AWS Lambda |

## Updating the articles

One command scrapes, embeds and uploads new articles. [`backend/UPDATING.md`](backend/UPDATING.md) has the full guide.

```bash
cd backend
uv sync                                  # one-time: create .venv
uv run inspect_pipeline.py check         # is the scraper still reading the site correctly?
uv run update_articles.py --dry-run      # what's new?
uv run update_articles.py                # scrape → embed → Pinecone → frontend data
```

## How the work is organised

AI agents do most of the development, working from shared documents:

- [`CLAUDE.md`](CLAUDE.md): how agents work in this repo
- [`GLOSSARY.md`](GLOSSARY.md): the terms we use, such as *arrival*, *re-post* and *staleness*
- [`DECISIONS.md`](DECISIONS.md): every decision, newest first, with the hard-to-reverse ones explained in [`docs/adr/`](docs/adr/)
- [`docs/plans/`](docs/plans/): the plan for each piece of work, with progress notes
- `writing_guide.md`: the house guide for anything written for people. It's kept private, so it isn't in the repo.
