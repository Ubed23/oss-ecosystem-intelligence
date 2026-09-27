# ADR 0003: OpenSSF Scorecard via REST, not BigQuery

## Status
Accepted

## Context
Scorecard is the only signal in this project computed by someone else. It is a
cross-check on a dashboard that otherwise marks its own homework, so it is
worth having — but it is a secondary signal, not a core metric.

Two ways to obtain it:

1. **BigQuery**, `openssf.scorecardcron.scorecard-v2_latest`. OpenSSF runs a
   weekly scan of the million most critical open source projects and publishes
   the results here. Broad coverage, one query.
2. **REST**, `api.securityscorecards.dev`. Only returns projects that opted in
   by setting `publish_results: true` in the Scorecard GitHub Action.

A dry run of the BigQuery query for 30 repositories estimated **85.42 GB**. The
nested `checks` array is read in full, and the `_latest` view spans all
partitions, so filtering to 30 rows does not reduce the scan.

At a weekly refresh that is roughly 340 GB per month against a 1 TB free
allowance — a third of the project's entire query budget, spent on a
cross-check.

## Decision
Use the REST API. Accept partial coverage.

Result: **26 of 30 repositories**. The four without published scorecards are
recorded as null, never zero.

## Consequences
- The cross-check chart covers 26 repositories, and says so.
- No BigQuery quota is consumed by this source, leaving the allowance for the
  historical backtest, which is a metric that carries weight.
- If coverage becomes a problem, the fallback is a narrower BigQuery query that
  selects only `score` and drops the `checks` array. That was not measured, but
  the array is the likely cost driver.
- A separate finding emerged while reviewing the data: Scorecard's overall
  score is dominated by supply-chain security practice, not activity. Every one
  of the six lowest-scoring repositories scored 10 on `check_maintained`. The
  meaningful comparator for this project is therefore `check_maintained`, not
  `scorecard_overall`. Recorded in docs/metrics.md.