# ADR 0002: GH Archive demoted to historical source

## Status
Accepted

## Context
The original design used GH Archive as the primary source for all activity
metrics, with the GitHub GraphQL API supplying only the detail stripped from
event payloads in October 2025 (ADR 0001).

Monthly event counts across 30 tracked repositories showed a steep,
implausible decline through 2026:

| month   | events |
|---------|--------|
| 2025-10 | 14,718 |
| 2025-11 | 15,042 |
| 2025-12 | 16,265 |
| 2026-01 | 17,787 |
| 2026-02 | 14,682 |
| 2026-03 | 12,374 |
| 2026-04 |  9,453 |
| 2026-05 |  6,619 |
| 2026-06 |  3,662 |
| 2026-07 |  2,120 |
| 2026-08 |  1,220 |

A 92% fall across projects including pandas, numpy and Airflow is not a real
change in developer behaviour. GH Archive's own issue tracker documents event
fidelity degrading from roughly the start of 2026, and a third party began
operating an independent GHArchive-compatible archive in September 2026 for
this reason.

`scripts/validate_gharchive.py` quantifies the gap per repository per month
against the GitHub search API. Results: `docs/gharchive_fidelity.csv`.

## Decision
- The GitHub GraphQL API becomes the primary source for every metric.
- Contributor cohorts are derived from GraphQL contribution records (issue and
  PR authorship, comments, reviews) rather than GH Archive events.
- GH Archive is retained only for pre-2026 history, where fidelity was intact,
  and is used solely for the archived-repository backtest.

## Consequences
- Stars, forks and raw pushes are no longer available as signals. Stars and
  forks were already excluded as measures of interest rather than work; direct
  pushes remain a documented blind spot of the bus factor metric.
- Cohort history is left-truncated at the backfill start date: a "first
  contribution" means first observed in the window, not first ever. Stated in
  the metric definitions.
- Ingestion depends on one rate-limited API rather than a bulk dataset, so the
  backfill takes hours of elapsed time rather than minutes.
- The fidelity comparison is kept as a dashboard exhibit. It is evidence of
  source validation, not a defect to hide.


Scorecard coverage is partial. The REST API only serves projects that opted into publishing results. The BigQuery dataset has broader coverage but the _latest view scans ~85 GB per query, which is not justified for a weekly cross-check on 30 repositories. Coverage: N of 30.