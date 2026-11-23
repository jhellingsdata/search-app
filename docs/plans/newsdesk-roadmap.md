# Newsdesk roadmap: P2–P4 and backlog

**Status:** outline. Each phase gets its own detailed plan file, like [newsdesk-p1.md](newsdesk-p1.md), when it starts.
**Decisions:** `DECISIONS.md` (rounds 1–4, 23 Nov 2026)

## P2: news and re-post ideas

**Goal:** the digest adds re-post ideas, Growth Lab priorities and the economics news to P1's homepage sections. The catalogue update runs automatically.

- **News sources.** Poll these feeds on every collect run. Keep only the headline and standfirst. Each feed below was checked on 23 Nov 2026 and returned items:

  | Source | Feed |
  |---|---|
  | BBC Business | `https://feeds.bbci.co.uk/news/business/rss.xml` |
  | BBC Economy | `https://feeds.bbci.co.uk/news/business/economy/rss.xml` |
  | BBC Politics | `https://feeds.bbci.co.uk/news/politics/rss.xml` |
  | FT UK economy | `https://www.ft.com/uk-economy?format=rss` |
  | FT UK politics | `https://www.ft.com/uk-politics?format=rss` |
  | FT global economy | `https://www.ft.com/global-economy?format=rss` |
  | Guardian Economics | `https://www.theguardian.com/business/economics/rss` |
  | Guardian Politics | `https://www.theguardian.com/politics/rss` |
  | The Economist, Britain | `https://www.economist.com/britain/rss.xml` (300 items, mostly older; keep only recent ones) |
  | Bank of England news | `https://www.bankofengland.co.uk/rss/news` |

- **Priority topics.** Store them in `newsdesk/priority_topics.yaml`, with a name, a one-line description and a few example phrasings for each. Draft the three agreed topics and have Josh review them.
- **Building the digest.** The three steps are in `DECISIONS.md` round 2:
  1. Claude groups the news into stories.
  2. Each story is embedded and matched against Pinecone, with the recency boost and exclusions applied.
  3. Claude picks the articles and writes a reason for each.

  Both Claude calls use Claude Opus 5.5 on Bedrock with structured output. Their prompts carry a short style brief based on `writing_guide.md`'s principles (answer first, concrete wording, British English), written fresh rather than copied, because the guide is private. Read the `claude-api` skill before writing the Bedrock client code.
- **Exclusions and repeats** are as in `DECISIONS.md` round 2.
- **Catalogue update automation**, all in `backend/` and `.github/workflows/`:
  - Add a minimum-age option to `update_articles.py` that skips posts whose `date_gmt` is less than 24 hours old.
  - Add a GitHub Actions workflow on cron `0 6 * * 1,4`. That's UTC, so it runs at 06:00 in winter and 07:00 in summer; either way it's before the digest.
  - The workflow runs the `check` → update → commit → `--upload-s3` sequence from `DECISIONS.md` round 3.
  - It authenticates to AWS with GitHub's OIDC, so it needs no stored AWS keys.
- **Alerts:** add an alarm for a news source that has returned nothing for 24 hours.
- **Setup questions:**
  - Bedrock: model access for Claude Opus 5.5, and whether to call it in eu-west-2 or through an EU cross-region inference profile.
  - Which OpenAI key pays for the Newsdesk's embeddings: the deployed search API's, or a new one?
  - Whether Pinecone can issue a read-only key for the Newsdesk.

## P3: key dates

- **ONS:** the release calendar API (`https://api.beta.ons.gov.uk/v1/search/releases`; check the upcoming-release filters when P3 starts), filtered to the release list in `DECISIONS.md` round 2.
- **Central banks:** `newsdesk/central_bank_dates.yaml` holds the Bank of England MPC, Fed FOMC and ECB monetary policy meeting dates for the next 12 months. Refresh it each December.
- **In the digest:** the key dates for the next 7 days, today's first, each with a re-post idea where one fits.

## P4: team rollout and take-up

- **Recipients:** add the ECO team. Store the list in SSM. In sandbox mode SES only sends to verified addresses, so either verify each address or request production access.
- **Reply-To:** decide whether replies go to Josh or to `office@economicsobservatory.com`.
- **Take-up:** record take-up and show a monthly take-up rate in the digest.

## Backlog

- **History page:** a page in the search app showing homepage history and past digests, behind a login because the frontend is public. Josh likes the idea; it's deferred.
- **Homepage position from WordPress:** read each ECO article's homepage position setting through the REST API as a second source of the layout, if the HTML parsing proves fragile.
- **Think tanks:** use them (Resolution Foundation, IFS, NIESR) as a research input, separate from the news.
- **Deploys from CI:** deploy the Newsdesk from GitHub Actions through OIDC.
- **API restart:** restart the Elastic Beanstalk API automatically after `--upload-s3`, so `/stats` and `/categories` never lag.

## Progress notes

- 2026-11-23: outline written at the end of scoping.
