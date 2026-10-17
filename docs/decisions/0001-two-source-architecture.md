# ADR 0001: Two ingestion sources after the Events API change

## Status
Accepted. Partly superseded by ADR 0002, which demoted GH Archive further.

## Context
The original design used GH Archive (an archive of the GitHub Events API,
queried through BigQuery) as the only source: cheap, bulk, and easy to
backfill.

GitHub announced changes to Events API payloads, scheduled for 7 October 2025
([changelog](https://github.blog/changelog/2025-08-08-upcoming-changes-to-github-events-api-payloads/);
the page is marked retired, so check the current status before relying on the
date). The announcement says that:

- slow-to-generate fields are removed from pull request events,
- commit summaries and counts are removed from push events, and
- `author_association` is removed from pull request, review, issue, comment and
  discussion events.

The removed data stays available through the REST API. GH Archive mirrors the
Events API, so it inherits every gap.

Metrics this project needs and the payload no longer carries: whether a
commenter is a maintainer (response time), what was merged and by whom (bus
factor), and issue labels (bug backlog).

## Decision
Use two sources, each for what it is good at:

- **GitHub GraphQL/REST API** for anything about authorship, merge status,
  labels and responses.
- **GH Archive** for breadth of activity and for history before the change.

## Consequences
- Ingestion depends on a rate-limited API (5,000 points per hour), so the
  backfill takes hours of elapsed time. It saves per-repository watermarks so a
  stopped run resumes.
- Raw data is stored as Parquet partitions and rebuilt through dbt.
- The backtest, which needs 2024 history, can only use activity counts: response
  times, merge status and labels cannot be reconstructed for that period.
- ADR 0002 later found GH Archive's own event counts degrading through 2026 and
  made the GraphQL API the primary source for every live metric.