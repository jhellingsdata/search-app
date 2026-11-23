# Decisions

One line per decision, newest first. Hard-to-reverse decisions also get an ADR in [`docs/adr/`](docs/adr/), linked from their line. Domain terms are defined in [`GLOSSARY.md`](GLOSSARY.md).

## 2026-11-23: Newsdesk scoping (round 4, final)

- **Digest layout:** the subject line carries the day's status, e.g. "ECO digest Tue 24 Nov: homepage red (3 days), 5 re-post ideas". The sections run in this order:
  1. status (three traffic lights)
  2. re-post ideas
  3. homepage map
  4. Growth Lab priorities
  5. economics news
  6. key dates
  7. New on ECO
  8. health line
- **P1 ends with a homepage-only digest:** status, homepage map and New on ECO. The SES and DNS setup moves into P1. It starts sending as soon as it's working, without waiting for a set amount of history.
- **Layout source:** the rendered homepage HTML is the record, because it shows what visitors see. Editors set each ECO article's homepage position in WordPress. Reading that setting through the REST API is on the backlog.
- **Writing:** anything people read (the digest's text and the prompts that produce it, READMEs, plans shared with the team) follows `writing_guide.md`.
- **The writing guide is private:** it's gitignored and stays on Josh's machine, because it names colleagues and refers to internal documents. `.worktreeinclude` lists it, so Claude Code copies it into the worktrees it creates. Prompts and other tracked files that need style rules state them in fresh wording, without copying the guide. Deploys can't expose it: Vercel serves only the built Next.js app in `frontend/`, the API image copies only `backend/app/`, and the Newsdesk package contains only its own code.
- **Missed-collect alert:** it fires after 9 hours without a successful collect, not 6. Collect runs pause for 8 hours overnight (22:00–06:00), so a 6-hour alert would go off every night.
- **Terms:** "position" means an ECO article's place in the order of article cards, matching the team's usage, and cards are identified by number. The earlier word "rank" is retired.

## 2026-11-23: Newsdesk scoping (round 3)

- **Claude access:** through Amazon Bedrock, using the Lambda's own AWS permissions. The `ANTHROPIC_API_KEY` in `.env` is billed to Josh personally, so deployed code must not use it. OpenRouter is the fallback if Bedrock access isn't granted. To check at P2 setup: model access for Claude Opus 5.5, and whether to call it in eu-west-2 or through an EU cross-region inference profile.
- **Catalogue update automated:** a GitHub Actions workflow runs on Mondays and Thursdays at 06:00 UK time.
  1. It runs `inspect_pipeline.py check`.
  2. If the check passes, it runs `update_articles.py`, which updates Pinecone, commits the dataset and frontend data to `main`, and runs `--upload-s3`. Posts published less than 24 hours earlier are skipped, to leave time for edits after publication.
  3. If the check fails, it stops and GitHub sends a failure email.

  The Elastic Beanstalk restart stays manual. Built alongside P2.
- **Alerts:** CloudWatch alarms send email through SNS when:
  - a run fails
  - there has been no successful collect for 6 hours
  - a snapshot doesn't come out as 16 cards, or has an unrecognised card (saved, but flagged as possible markup drift)
  - a news source has returned nothing for 24 hours

  The digest ends with a one-line health check.
- **Fetching:**
  - Make requests as close to a normal browser's as possible.
  - Use APIs and feeds wherever they exist: the WordPress REST API, RSS, the ONS API and GOV.UK's bank holidays JSON. Parse HTML only where there is no API, such as the homepage layout.
  - If requests get blocked, the Growth Lab research pipeline's proxies (Lambda, residential, mobile) are available on request. Their details never go in the repo. For the ECO homepage, a Cloudflare rule is also an option.
- **Testing:**
  - offline pytest, using saved real pages and feeds as fixtures, with stand-in OpenAI, Pinecone and Claude clients
  - layout parsing, arrival detection, staleness and exclusions are written test-first
  - a dry-run command writes the digest to a local HTML file instead of sending it
  - agents run the tests before calling any work done
- **Search app history page:** a good idea, deferred to the backlog.
- **Git:** commits carry no Claude co-author trailer or other Claude attribution.

## 2026-11-23: Newsdesk scoping (round 2)

- **Architecture:** one Lambda function on AWS, with its state in a SQLite file in S3 and raw responses archived next to it. See [ADR 0001](docs/adr/0001-newsdesk-serverless-on-aws-with-sqlite-in-s3.md).
- **Runs:** one Lambda function (Python 3.13) runs on two schedules, in UK time:
  - *collect* every 2 hours from 06:00 to 22:00, every day: takes a homepage snapshot and polls the news sources.
  - *digest* on weekdays at 07:30: runs a collect, then sends a digest covering the news since the previous one.

  Only one run happens at a time.
- **Infrastructure:**
  - an AWS SAM template in `newsdesk/`, region eu-west-2
  - the package is built with uv from Linux wheels, so Docker isn't needed
  - secrets are kept in SSM Parameter Store
  - deploys are run by Josh, or by an agent when he asks
- **Email:**
  - sent with Amazon SES from a domain identity on `newsdesk.economicsobservatory.com`: `digest@newsdesk.economicsobservatory.com`, with replies going to Josh
  - mail on the root domain, hosted by GoDaddy and including `office@`, is untouched
  - SES starts in sandbox mode, sending only to verified addresses
  - the AWS side is expected to cost under $1 a month
- **Homepage map:** the digest draws the 16 cards as an HTML table, with no images. Each article card shows its position, a short title and a colour for working days on the homepage, and arrivals since the last digest get a badge. Fixed cards are greyed out.
- **New on ECO:** the digest lists the ECO articles published in the last 7 days, each with its current card or "not on the homepage".
- **Recommendation exclusions:**
  - never recommend an article that is on the homepage now, that arrived on the homepage in the last 30 days, or that is in the "News" category (ECO's own announcements)
  - an article recommended in the previous 5 working days may be recommended again only if it is still highly relevant and hasn't arrived on the homepage since; it is then marked as a repeat
- **News sources:**
  - *Final list:* BBC (business, economy, politics); FT (UK economy, UK politics, global economy); Guardian (economics, politics); The Economist (Britain); Bank of England news.
  - *Ruled out:*
    - The Times: no public feed, and paywalled.
    - Telegraph business: checked on 23 Nov, it runs about one story a day with front-page-style framing.
    - Bloomberg: mostly global markets.
    - Think tanks: commentary rather than news; a possible later input.
- **How the digest is built:**
  1. Claude groups the news items since the last digest into stories, drops stories with no economic angle (keeping any that match a priority topic), ranks them, and writes the summaries.
  2. Each story's summary is embedded with OpenAI `text-embedding-3-small` and matched against Pinecone, giving about 10 candidate articles per story, then the recency boost and the exclusions are applied.
  3. Claude picks 0–2 articles per story and writes a one-line reason for each.

  Both Claude calls use Claude Opus 5.5 with structured output, costing about $5 a month.
- **Key dates (P3):**
  - *ONS:* the release calendar API, filtered to a set list (CPI, CPIH and PPI; monthly and quarterly GDP; the labour market; public sector finances; retail sales), plus any release matching a priority topic.
  - *Central banks:* Bank of England MPC, Fed FOMC and ECB meeting dates in a YAML file in the repo, updated each year.
  - *In the digest:* the next 7 days, each with a recommendation where one fits.
- **Catalogue lag:** the Newsdesk reads WordPress live for arrivals and New on ECO, and the digest says when the Pinecone index is behind. The catalogue update should be automated so it's never more than a few days behind (see round 3).
- **Feedback (P4):** automatic only. When a recommended article arrives on the homepage within 5 working days, it counts as taken up, and the digest reports a monthly take-up rate. The email has no rating links.

## 2026-11-23: Newsdesk scoping (round 1)

- **Agent docs:** `CLAUDE.md` (orientation and rules), `GLOSSARY.md` (domain terms only), this file, `docs/adr/` (hard-to-reverse decisions only) and `docs/plans/` (one file per piece of work, with checkbox steps that agents update). Work is tracked in the repo, not in GitHub Issues.
- **Code location:** `news-recommender/` is replaced by `newsdesk/`, a separate uv project on Python 3.13. It reads the Pinecone index and the WordPress REST API, and imports nothing from `backend/`. The August 2025 OneDrive prototype is not ported.
- **Hosting:** AWS (Lambda and EventBridge) in the existing account, chosen over GitHub Actions (free for a public repo, but public logs and loose cron timing) and Claude cloud routines.
- **Phasing:** P1 homepage tracker, deployed first so history builds up. P2 digest v1, sent only to Josh: homepage staleness, news summary, recommendations, priority-topic highlights. P3 key dates. P4 team rollout and a feedback loop.
- **Homepage tracking:** each snapshot records the full layout of all 16 cards (each card's number and content: the fixed cards, the promo card when shown, and each ECO article with its position), so the digest can draw a map of the homepage.
- **Arrivals:** new article and re-post are told apart by publish date. WordPress keeps the original publish date on re-posts (checked 23 Nov: the 2020 pandemics article is still dated 29 June 2020). See `GLOSSARY.md`.
- **Homepage staleness:** the target is at least one arrival per working day. Green at 0 working days without one, amber at 1, red at 2 or more. The digest also shows new articles in the last 7 days against the usual 3–5, and flags a lead article that has stayed 3 or more working days. To be refined once it's running.
- **Chart staleness:** amber at 2 working days, red from 3.
- **News sources (initial):** BBC (business, economy, politics), FT (UK, global economy), Guardian (economics, politics) and Bank of England news. Only the headline and standfirst are used; full articles are not scraped.
- **Matching:** recommendations are made per story, not per headline. About 5 stories, each with 0–2 recommendations, about 5 in total.
- **Recency:** rank by similarity with a mild boost for ECO articles from the last 2 years and no hard cut-off. Show each recommendation's publish date, and add a "check figures still hold" note to articles over 2 years old.
- **Priority topics:** kept in a YAML file in the repo. They affect the news side only (matching stories are always included and highlighted), not how ECO articles are ranked. Initial list: prices and price measurement; English devolution and Mayoral Strategic Authorities; regional growth in the devolved nations.
- **Digest delivery:** weekdays at 07:30 UK time, to Josh only until P4. Recipient addresses are kept in secrets, never in the repo. Josh controls the Cloudflare DNS for economicsobservatory.com.
