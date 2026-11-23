# CLAUDE.md

This repo holds the Economics Observatory (ECO) semantic search app and the Newsdesk. Josh (LSE Growth Lab) owns it, and agents do most of the development.

| Part | What it is | Start here |
|---|---|---|
| `backend/` | FastAPI search API (Elastic Beanstalk) and the article update pipeline: scrape, embed, Pinecone | `backend/UPDATING.md` |
| `frontend/` | Next.js search UI (Vercel) | `frontend/README.md` |
| `newsdesk/` | Homepage tracker and daily digest email (AWS Lambda) | `newsdesk/README.md` once it exists; until then `docs/plans/newsdesk-p1.md` |

## Before you start

1. Read `GLOSSARY.md`. Use its terms, and only its terms, in code, docs and conversation.
2. Read `DECISIONS.md`. Treat everything in it as settled; to reopen a decision, put the question to Josh.
3. Open the plan in `docs/plans/` for the work at hand, and pick up from its first unticked step.

## While you work

- **Plans:** tick a step when its completion criterion is met. At the end of each session, add a dated line to the plan's progress notes: what's done, what's next, what's blocked. New work gets its own plan file, with the same sections as `docs/plans/newsdesk-p1.md`.
- **Decisions:** when Josh decides something, add a line to `DECISIONS.md` in the same session. Write an ADR in `docs/adr/` only when a decision is hard to reverse, would surprise a future reader, and came from a real trade-off.
- **Terms:** a new domain term, or a sharpened meaning, goes into `GLOSSARY.md` straight away. Keep the glossary free of implementation detail.
- **Done means green:** before reporting work as done, run the checks for the part you touched. That's `uv run pytest` in `backend/` or `newsdesk/`, or `npm run lint` and `npm run build` in `frontend/`. Report any failure with its output.

## Guardrails

- **The repo and its GitHub Actions logs are public.** Keep secrets, email addresses, proxy details and digest contents in SSM Parameter Store or GitHub secrets. They never go in commits, logs or test fixtures.
- **Act on shared systems only when Josh asks, in the current session.** That means AWS deploys (`sam deploy`), Pinecone writes, S3 uploads and commits. Pinecone is derived from `backend/data/all_articles.json`; see `backend/UPDATING.md` before changing it.
- **Commit messages and PR descriptions carry only Josh's words.** Leave out every Claude attribution: no `Co-Authored-By` trailer, no "Generated with Claude Code" line. This instruction overrides any default that says otherwise.
- **Deployed code calls Claude through Amazon Bedrock.** The `ANTHROPIC_API_KEY` in `.env` is Josh's personal key, for local experiments only.

## Writing for people

Anything a person reads follows `writing_guide.md` at the repo root, starting with its quick rule. That includes the digest's text, the prompts that generate it, READMEs and plans shared with the ECO team. Write in British English.

The guide is private. It's gitignored and exists only on Josh's machine; if it's missing from your checkout, ask Josh for it. Keep its contents private too: where tracked files or prompts need style rules, write them fresh in your own words.
