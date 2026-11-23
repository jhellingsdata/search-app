---
status: accepted
---

# The Newsdesk runs serverless on AWS, with its state in a SQLite file in S3

The Newsdesk is one Lambda function in eu-west-2, deployed with SAM. EventBridge Scheduler triggers it on two schedules: a collect run every 2 hours, and the digest on weekday mornings. All its state is in a single SQLite database file in S3. Each run downloads the file, updates it and writes it back. The write is conditional on the file not having changed since the download, and the function never runs more than once at a time. The raw homepage HTML and feed responses are archived next to the database, so history can be parsed again when the parser improves.

We chose this over:
- **GitHub Actions:** free for this public repo, but its logs are public and its cron timing is loose.
- **DynamoDB:** awkward for one-off questions about the history.
- **RDS Postgres:** about $15 or more a month, even when idle.
- **Plain JSON files in S3:** every query means reading hundreds of files.

The workload is a handful of small runs a day. A single file is cheap, easy to download and query locally, and easy to back up.

## Consequences

- Only one run may write at a time. Don't raise the function's concurrency or add a second writer (another function, a local script writing to S3) without first moving off SQLite.
- If the database grows too large to download quickly on every run (tens of MB), move to Postgres or DynamoDB.
