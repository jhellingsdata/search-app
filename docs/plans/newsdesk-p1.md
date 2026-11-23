# Newsdesk P1: homepage tracker and homepage-only digest

**Status:** not started
**Decisions:** `DECISIONS.md` (rounds 1–4, 23 Nov 2026) and [ADR 0001](../adr/0001-newsdesk-serverless-on-aws-with-sqlite-in-s3.md)
**Later phases:** [newsdesk-roadmap.md](newsdesk-roadmap.md)

## Goal

A Lambda function snapshots the ECO homepage every 2 hours and records arrivals. Each weekday at 07:30 it emails Josh a digest of the homepage only: status lights, a homepage map and New on ECO. History starts building from the first deploy, and P2 adds the news on top.

## Done when

- The collect run has run on schedule for 3 consecutive working days with no unexplained alarm.
- Josh has received the 07:30 digest on each of those days, and its status lights agree with a manual check of the homepage.
- `uv run pytest` passes in `newsdesk/`.
- `newsdesk/README.md` explains how to set up, test, deploy and operate the Newsdesk, following `writing_guide.md`.

## Steps

Each step ends on its completion criterion. Steps 1–8 run entirely locally; steps 9–11 involve AWS and Josh.

- [ ] **1. Scaffold `newsdesk/`.**
  - Set up a uv project on Python 3.13 with a `src/newsdesk/` package.
  - Add a `newsdesk` command-line entry point and a `tests/` folder.
  - Runtime dependencies: `requests`, `beautifulsoup4` (use the `html.parser` backend, which is pure Python and keeps Lambda packaging simple), `boto3` and `jinja2`. Dev dependency: `pytest`.
  - Add `newsdesk/local/` to `.gitignore` (it's already there) for local database copies and dry-run output.

  *Done when* `uv run newsdesk --help` and `uv run pytest` both run.

- [ ] **2. Capture fixtures.**
  - Save the live homepage HTML, trimmed to the `home__blocks-grid` element, as `tests/fixtures/homepage_<date>.html`.
  - From it, make edited variants:
    - the promo card shown, with 12 article cards
    - a different homepage chart
    - a reshuffle, where existing articles change position but none arrive
    - one new article arriving at position 1
    - one re-post arriving at position 4
  - Save a page of the WordPress `question` API response as a fixture too.

  *Done when* every variant is in `tests/fixtures/` with a one-line comment at its top saying what was changed.

- [ ] **3. Parse the layout (test first).**
  - Turn the HTML into a snapshot of 16 cards. Each card has its number and kind (article, Data Hub, homepage chart, Magazine or promo), plus its URL and title.
  - Each article gets its position.
  - The chart card also records its chart ID and the ECO article it links to.
  - Any card that matches no known kind is a promo card, and its link is recorded.
  - A snapshot is flagged unless it has exactly 16 cards, one each of the three fixed cards, 12 or 13 article cards and at most one promo card.

  See *Homepage markup* below for the details.

  *Done when* the tests cover every fixture and flag a deliberately broken one.

- [ ] **4. Look up articles in WordPress.**
  - Fetch the `question` index (all published ECO articles: id, link, `date_gmt`, `modified_gmt`, title) and cache it in the database.
  - Refresh it on the first collect of each day, and again whenever a snapshot contains an article URL the cache doesn't know.
  - Match articles by link, not by the API's `slug` field (see `backend/UPDATING.md`).

  *Done when* every article in the live snapshot resolves to a post ID and a publish date.

- [ ] **5. Count working days.**
  - Fetch the England and Wales bank holidays from `https://www.gov.uk/bank-holidays.json` and cache them in the database. If the fetch fails, use the last cached copy.
  - Provide `working_days_between(a, b)`.

  *Done when* tests cover a normal week, a weekend (Friday to Monday is one working day), Christmas and the Easter weekend.

- [ ] **6. Detect arrivals and measure staleness (test first).**
  - Compare each snapshot with the previous good one.
    - An ECO article that wasn't anywhere on the homepage before is an arrival.
    - It's a new article if it was published within the previous 7 days, and a re-post otherwise.
    - An article that only changes position is not an arrival.
  - Calculate:
    - homepage staleness, with the thresholds in `DECISIONS.md`
    - chart staleness
    - new articles in the last 7 days
    - how long the lead article has been at position 1
  - **Bootstrapping, before any arrival has been seen.** Estimate when the last arrival happened as the latest publish date or modified date among the ECO articles on the homepage. Estimate when the chart went up from its `user-charts` publish date. Label both as estimates until real history replaces them.

  *Done when* the tests cover each fixture transition, and the bootstrap figures for the live homepage match a manual check.

- [ ] **7. Store state and archive raw pages.**
  - Keep all state in one SQLite file: snapshots, cards, articles, arrivals, bank holidays and sent digests.
  - Sync the file with S3 as ADR 0001 describes: download it, write it back with `IfMatch` set to the downloaded copy's ETag (`IfNoneMatch='*'` the first time), and fail loudly if that conditional write is rejected.
  - Archive every fetched homepage as gzip under `raw/homepage/YYYY/MM/DD/HHMM.html.gz`.
  - Add a local mode that keeps the database at `newsdesk/local/newsdesk.db` and uses no S3.

  *Done when* `uv run newsdesk collect --local` builds up snapshots across repeated runs, and a test shows that a rejected conditional write raises an error.

- [ ] **8. Render the digest.**
  - Write the HTML email as a Jinja2 template with inline CSS and table layout, plus a plain-text version.
  - Sections, in the order `DECISIONS.md` gives:
    1. status: three traffic lights, plus a lead-article flag
    2. homepage map
    3. New on ECO: ECO articles published in the last 7 days, each with its card or "not on the homepage"
    4. health line
  - Subject format: "ECO digest Tue 24 Nov: homepage red (3 days)".
  - The homepage map follows the desktop layout. Work the layout out from a Playwright screenshot of the live homepage, not by guessing.
  - The wording follows `writing_guide.md`.
  - `uv run newsdesk digest --local --dry-run` writes the email to `newsdesk/local/digest-<date>.html` instead of sending it.

  *Done when* Josh has opened a dry-run digest built from live data and approved how it looks.

- [ ] **9. Define the infrastructure.**
  - Write `newsdesk/template.yaml` (SAM, region eu-west-2) containing:
    - **S3:** a private bucket with versioning on, which gives the SQLite file free backups.
    - **Lambda:** one Python 3.13 arm64 function, with reserved concurrency 1 and a 120-second timeout.
    - **Schedules:** two EventBridge Scheduler schedules in `Europe/London` time:
      - collect: `cron(0 6-22/2 * * ? *)`
      - digest: `cron(30 7 ? * MON-FRI *)`
    - **Bank holidays:** the digest run exits early on a bank holiday, and the next digest covers the gap.
    - **SES:** an email identity for `newsdesk.economicsobservatory.com`, with Easy DKIM and MAIL FROM set to `mail.newsdesk.economicsobservatory.com`.
    - **Alerts:** an SNS topic with an email subscription, and CloudWatch alarms for:
      - any function error
      - no successful collect for 9 hours (the run publishes a custom metric; treat missing data as breaching)
      - one or more flagged snapshots
    - **Logs:** kept for 30 days.
  - Email addresses come in as deploy-time parameters (`--parameter-overrides`) or from SSM, and never appear in `template.yaml` or `samconfig.toml`.
  - Package the function with a script that runs `uv export` and then `uv pip install --target` with `--python-platform aarch64-manylinux2014 --python-version 3.13 --only-binary :all:`. That needs no Docker.

  *Done when* `sam validate --lint` passes and the package script builds a zip.

- [ ] **10. [Josh] Do the one-off setup.** An agent can generate an interactive walkthrough with the `wizard` skill.
  1. ~~Install the SAM CLI: `brew install aws-sam-cli`.~~ Done 23 Nov (SAM CLI 1.174.0, AWS CLI 2.42.1).
  2. ~~Set up AWS credentials.~~ Done 23 Nov. The default profile signs in to eu-west-2, in the same account as the search API's Elastic Beanstalk environment.
  3. Run the first `sam deploy --guided`, then confirm the SNS subscription email.
  4. Add the DNS records from the stack outputs in Cloudflare, as DNS only (grey cloud): 3 DKIM CNAMEs, plus an MX and an SPF TXT record on `mail.newsdesk`.
  5. Verify his own address in SES, which is in sandbox mode.

  *Done when* the SES console shows the domain identity as verified.

- [ ] **11. Deploy and verify.**
  1. Invoke collect by hand, and check the database and raw archive in S3.
  2. Invoke digest by hand, and check that the email arrives and renders correctly in Outlook and Gmail.
  3. Trip each alarm once, e.g. by pointing the function at an unreachable URL, and check that the email arrives.
  4. Watch 3 working days of scheduled runs.

  *Done when* every point under **Done when** at the top holds.

## Reference

### Homepage markup (checked 23 Nov 2026)

- **Cards** are elements in `.home__blocks-grid` carrying `home__blocks-item-N`. The Data Hub card's classes say `custom-count-2` instead, and some article cards sit inside `home__blocks-item-group` wrappers.
- **Card 1:** the lead article (`--style1`). Its category label reads "New Post", which is the site's label only; the Newsdesk classifies by publish date.
- **Card 2:** the Data Hub (`a.home__events`, linking to `/explore`).
- **Card 5:** the homepage chart (`--style5`, with `.home-pinned-chart` and `data-chart-id`). It links to an ECO article. On 23 Nov this was chart 35250, "UK GDP growth by sector", a `user-charts` post created on 12 Nov 2026 (`/wp-json/wp/v2/user-charts/<id>`).
- **Card 7:** Magazine. Its label reads "MAGAZINE" and it links to a magazine page, not a `question` post.
- **Every other card** on 23 Nov was an ECO article: 13 article cards, with the promo card off. When the promo card is on, it sits below the Data Hub card and pushes the articles down, leaving 12. Its markup hasn't been seen: it wasn't in about 100 Wayback snapshots.
- **Caching:** Cloudflare caches the page for about 10 minutes, which is fine at a 2-hour interval.
- **Requests:** send browser-like headers (`User-Agent`, `Accept`, `Accept-Language: en-GB`). If requests from AWS get blocked, ask Josh: the Growth Lab research pipeline's proxies, or a Cloudflare rule, can fix it.

### WordPress

- ECO articles are the `question` post type: `/wp-json/wp/v2/question?per_page=100&_fields=id,link,date_gmt,modified_gmt,title`, about 12 pages.
- Re-posts keep their original publish date. Changing an article's homepage position bumps its `modified_gmt`, which is why the bootstrap in step 6 can use it.
- Use `date_gmt` rather than `date`, which is in site local time.

### Open defaults

These are proposed values not yet confirmed by Josh. Confirm them at step 8.
- **New-articles light:** green at 3 or more in 7 days, amber at 1–2, red at 0.
- **Bank holidays:** no digest is sent on a bank holiday.

## Progress notes

- 2026-11-23: plan written at the end of scoping. Nothing built yet.
- 2026-11-23: Josh installed the SAM CLI and AWS CLI and set up credentials (step 10, items 1–2). The AWS skills are installed, and so is the `aws-mcp` server (`claude mcp list` shows it connected); its tools appear in sessions started after the install. `.worktreeinclude` copies `writing_guide.md` and `.env` into new worktrees.
