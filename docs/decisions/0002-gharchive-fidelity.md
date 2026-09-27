# ADR 0002: GH Archive demoted to historical source

## Status
Accepted

## Context
The original design used GH Archive as the primary source for all activity
metrics, with the GitHub GraphQL API supplying only the detail stripped from
event payloads in October 2025 (ADR 0001).

Monthly event counts across the 30 tracked repositories showed a steep,
implausible decline through 2026:

| month   | archive events | API items created | ratio |
|---------|---------------:|------------------:|------:|
| 2025-10 |         24,139 |             6,127 |  3.94 |
| 2025-11 |         23,147 |             5,354 |  4.32 |
| 2025-12 |         25,642 |             5,470 |  4.69 |
| 2026-01 |         28,367 |             6,338 |  4.48 |
| 2026-02 |         22,320 |             6,345 |  3.52 |
| 2026-03 |         18,201 |             7,758 |  2.35 |
| 2026-04 |         13,160 |             6,656 |  1.98 |
| 2026-05 |          8,469 |             6,868 |  1.23 |
| 2026-06 |          5,723 |             6,214 |  0.92 |
| 2026-07 |          2,522 |             7,895 |  0.32 |
| 2026-08 |          1,277 |             7,749 |  0.16 |

A 95% fall across projects including pandas, numpy and Airflow is not a real
change in developer behaviour. The API line stays flat at roughly 7,000 items
per month across the same period, which isolates the problem to the archive.

GH Archive's own issue tracker documents event fidelity degrading from around
the start of 2026, and a third party began operating an independent
GHArchive-compatible archive in September 2026 for this reason.

The comparison is reproduced as a model, `fct_source_fidelity`, so the evidence
is rebuilt on every run rather than asserted once.

## Decision
- The GitHub GraphQL API becomes the primary source for every live metric.
- Contributor cohorts are derived from GraphQL contribution records (issue and
  PR authorship, comments, reviews) rather than GH Archive events.
- GH Archive is retained only for pre-2026 history, where fidelity was intact,
  and is used solely for the archived-repository backtest and for this
  fidelity exhibit.

## Consequences
- Stars, forks and raw pushes are no longer available as signals. Stars and
  forks were already excluded as measures of interest rather than work; direct
  pushes remain a documented blind spot of the bus factor metric.
- Cohort history is left-truncated at the backfill start date: a "first
  contribution" means first observed in the window, not first ever.
- Ingestion depends on one rate-limited API rather than a bulk dataset, so the
  backfill takes hours of elapsed time rather than minutes.
- The fidelity comparison is kept as a dashboard exhibit on the methodology
  page. It is evidence of source validation, not a defect to hide.