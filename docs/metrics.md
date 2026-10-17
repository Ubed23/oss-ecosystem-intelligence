# Metric definitions

Every metric is defined here before it is built. Where a definition is
contested, the argument is recorded rather than buried in SQL.

Scope: 30 repositories in the Python data and ML ecosystem.
Analysis window: from **2025-10-01**.
Refresh: manual today (`dbt build`, then `scripts/to_sheets.py`). A daily
GitHub Actions schedule is planned but not yet running. Not real-time — see
"Freshness" below.
Last reviewed: 16 Oct 2026.

---

## Sources and what each is trusted for

| Source | Used for | Trusted? |
|---|---|---|
| GitHub GraphQL API | Every live metric | Yes — authoritative |
| GitHub REST (releases) | Cadence, regression ratio | Yes |
| OpenSSF Scorecard | Independent cross-check | Yes, but partial coverage (26/30) |
| GH Archive (BigQuery) | Historical backtest and the fidelity exhibit only | **No** for recent data — see ADR 0002 |

---

## The metrics

"Items" means issues and pull requests together. "Items opened" counts both;
"PRs merged" counts pull requests only.

### Bus factor (50%)
**Definition.** The fewest non-bot authors accounting for at least 50% of
merged pull requests in the analysis window.

**Method.** Each author's share of merged PRs, sorted descending, running
total, count how many authors it takes to cross 50%. Ties break on author name
so the result is deterministic — without that, ties reorder between runs and
the "biggest movers" chart fills with noise.

**Blind spot.** Maintainers who push directly to the main branch never open a
pull request and are invisible here. A project with one PR author may have
several people committing.

**Null handling.** Null means no merged PRs in the window — absence, not zero.
Never coalesced to 0, which would label a dormant project as maximally
concentrated. In the score, null ranks worst: no merged PRs is genuinely
concerning.

### Maintainer activity
**Definition.** Distinct authors of pull requests merged in the last 90 days.

**Null handling.** No merged PRs counts as zero and ranks worst.

### Time to first response (P50 / P90)
**Definition.** Hours from an issue or PR being opened to the first comment or
review by an OWNER, MEMBER or COLLABORATOR who is **not** the person who
opened it.

**Why exclude the author.** A maintainer opening their own issue and commenting
on it would otherwise record a response time near zero and drag the project's
median down.

**Right-censoring.** Items with no reply have no response time. Excluding them
silently — which a naive median does — makes a project that ignores 80% of its
issues look *faster* than one answering everything within a week. The dashboard
therefore always shows median response time **next to** the unresponded rate.
Neither number means anything alone. The same effect makes the most recent
months look faster than they are, because the slowest replies have not
happened yet.

**Negative values.** One row in ~116,000 had a first response predating
creation. This happens when an issue is transferred between repositories
(comments survive, `createdAt` resets) or converted from a discussion. Recorded
as **null, not zero** — zero would read as "answered instantly", which is
better than any real value. When a value is impossible, record absence rather
than inventing a plausible number.

**Blind spot.** Replies outside GitHub — Slack, mailing lists, Discourse — are
not counted.

### Unresponded rate
Share of items with no maintainer response after **7 days**
(`response_sla_days`). Reported alongside response time, never separately. When
pooled across repositories on the dashboard it is weighted by items opened, so
a repository with three issues does not count as much as one with three
thousand.

### Bug backlog
**Definition.** Count of open issues whose labels normalise to `bug` or
`regression`. Only issues count; pull requests carrying a bug label are
excluded.

**Label normalisation.** Projects use different vocabularies — "bug",
"type: bug", "kind/bug", "defect", and project-specific ones such as
"kind:bug", "00 - bug", "bug v2", "type-bug" and "#bug". `seeds/label_map.csv`
maps them by exact, case-insensitive match. Unmapped labels are **dropped, not
guessed**. Labels that describe pull requests (for example "change:bugfix"),
programmes or unconfirmed reports (for example "type-possible-bug") are
deliberately not mapped.

**Blind spot.** Counts depend on each project's own labelling. A project that
labels only some of its bugs scores better than it should, and a project that
labels none shows zero. A repository with no recognised bug opened in the 12
months scores a neutral 0.5 on this component, never the best score. At the
time of writing that applies to duckdb, requests and python-bigquery
(archived); seaborn recorded one. Compare a repository with itself over time,
not with other repositories.

### Contributor retention (cohorts)
**Definition.** Of the people whose first observed contribution to a repository
fell in month M, what share was active again N months later?

**What counts as a contribution.** Opening an issue or PR, commenting,
reviewing. **Not** stars, forks or watches — those measure interest, not work,
and including them would let a viral tweet look like community growth.

**What the number measures.** Activity in month N, not survival: someone silent
in month 2 and active in month 3 counts at month 3, so a curve can tick up.

**Cohort table.** Covers months 0 to 12 after the first contribution, limited
to cells that fall before the current month; month 0 is always 100%. A cohort
in which nobody returned counts as zero, not as a missing row. Cells that would
fall in the current, unfinished month are excluded
(`tests/assert_cohort_grid_valid.sql` enforces this). The months published to
the dashboard are set in `scripts/to_sheets.py`.

**In the score.** Month 3 only: people active in the third month after their
first observed contribution, pooled across cohorts and weighted by cohort size.
It is scored only where at least 100 people sit behind the figure
(`min_retention_sample`); below that the component scores a neutral 0.5,
because a rate from a handful of people is noise.

**Left truncation.** "First contribution" means *first observed since
2025-10-01*, not first ever. Someone who contributed in 2019 and returned last
month is counted as a newcomer. This inflates early cohort sizes and is stated
on the dashboard.

**Scope change.** Contributions now come from the GraphQL API rather than GH
Archive (ADR 0002), so direct pushes are no longer counted. Narrower, but for
"does this project convert newcomers into regulars" it is arguably the better
definition.

### Post-release regression ratio
**Definition.** Bugs opened in the 14 days after a release, divided by the
count predicted from the prior 90 days' bug rate.

```
expected = bugs_in_prior_90_days × (14 / 90)
ratio    = bugs_in_14_days_after / expected
```

Above 1 means more bug reports than usual followed that release. Above 2 is
worth investigating.

**Caveat, stated on the dashboard.** This is correlation. A release and a bug
spike can share a cause: a big release draws attention, and attention produces
reports.

**Overlapping windows.** Follow-up windows of releases close together overlap,
so one bug can fall under several releases and totals are not distinct bugs.
Compare the two bars for a repository, or use a pooled ratio, rather than
reading a sum as a count of bugs.

**What the dashboard judges.** Only releases with at least 2 expected bugs,
because a single report on a tiny expectation swings the ratio wildly, and only
releases whose 14-day window fits inside the data (the `window_complete` column
in the published `releases` sheet). The outcome bands on the dashboard (below
0.75, up to 1.5, up to 3, above 3) are a presentation choice, not a standard.

**Null handling.** Null when the baseline window held no bugs — division
guarded, not faked.

### Release cadence
Median days between non-prerelease, non-draft releases. Prereleases are
excluded because release candidates fire every few days and would make a
slowing project look healthy. Not a component of the health score.

**Blind spot.** Projects that tag releases without creating GitHub Release
objects return nothing. Their cadence is null, which must not be read as "never
releases".

---

## Window filtering: which metrics filter, and why not all of them

Raw data extends back to 2006 because pagination was by `updated_at`. Items
created before the window are present, but they are a **biased sample** — only
the ones touched recently came back.

| Metric type | Filtered on `created_at >= analysis_start`? | Reason |
|---|---|---|
| Items opened, PRs merged, response time, bugs opened | **Yes** | Counting "issues opened in 2019" from a biased sample is meaningless |
| Open bug backlog | **No** | An issue from 2019 still open today is genuinely part of today's backlog |

In `fct_repo_health_monthly`, the `bugs_opened` CTE filters and the `backlog`
CTE does not. That distinction is deliberate.

---

## The health score

**Percentile ranks, not raw values.** You cannot average a bus factor of 3, a
response time of 41 hours and a backlog of 180 issues — different units,
different ranges, response time would swamp everything. Each component is
converted to a percentile rank within the tracked set, so every input is 0–1
and comparable.

**Components and weights.** Six components, weighted in
`seeds/score_weights.csv`:

| Component | Balanced | Reliability-heavy | Community-heavy |
|---|---:|---:|---:|
| Bus factor | 0.20 | 0.15 | 0.30 |
| Maintainer activity | 0.15 | 0.10 | 0.25 |
| Response time | 0.20 | 0.30 | 0.10 |
| Unanswered share | 0.15 | 0.20 | 0.10 |
| Bug backlog | 0.15 | 0.20 | 0.05 |
| Contributor retention | 0.15 | 0.05 | 0.20 |

Each column sums to 1.00. Weights live in the seed, never hard-coded. This
makes the sensitivity analysis a one-command job and lets the weights be
exposed as Tableau parameters so a viewer can change the priorities
themselves.

**What the score therefore claims.** "Relative to these 30 repositories", not
"objectively healthy". That is the honest reading and it is the one printed on
the dashboard.

**Tiers are quartiles, not fixed thresholds.** Fixed cutoffs (25/50/75) put 29
of 30 repositories in the middle two bands, because percentile-rank composites
cluster near the middle by construction. Quartiles of the tracked set mean
"critical" = bottom quartile relative to these 30, which matches what the score
actually measures. The tiers are Critical, At Risk, Stable and Healthy, and
they are brittle: a small change in weights moves repositories across a
quartile boundary.

**Trailing 90 days for the current snapshot.** Responsiveness and merge
activity use a trailing 90-day window ending at the build time, not the latest
calendar month. A quiet month would otherwise leave those metrics null. As a
consequence, the same data rebuilt on a different day gives slightly different
scores.

**Null direction is set per metric.** Bus factor: no merged PRs is genuinely
concerning, so null ranks worst. Maintainer activity: no merged PR authors
counts as zero and ranks worst. Response time, unanswered share, bug backlog
(no bugs recognised in 12 months) and retention (fewer than 100 people in the
month-3 cohorts): no usable data scores a neutral 0.5, ranked in its own group
so it never takes the best or worst place. The reason is the same in every
case: "no data" must not be scored as if it were "good data" or "bad data".

**The monthly trend score is a different measure.** `fct_health_score_monthly`
ranks every repository-month against every other repository-month, so a genuine
improvement across the whole portfolio moves the line. It has no retention
component (monthly retention cannot be rebuilt without leaning on the
left-truncated early months, so contributor activity stands in), its bus factor
is a trailing 12-month figure attached to every month, and it excludes the
current calendar month. Its scale therefore differs from the current snapshot's,
and the two will not match.

---

## Coverage and data-quality notes

**Scorecard: 26 of 30.** The REST API only serves projects that opted in with
`publish_results: true`. The BigQuery dataset has broader coverage but the
`_latest` view scans 85 GB per query — 340 GB/month for a weekly cross-check on
30 repositories, against a 1 TB allowance. Not justified for a secondary
signal. See ADR 0003.

**Scorecard overall vs Maintained.** Scorecard's overall number is dominated by
supply-chain security practice (branch protection, pinned dependencies, signed
releases). A vigorously maintained project can score 4.7 for not pinning its
GitHub Actions. The meaningful comparator for this project is
`check_maintained`, not `scorecard_overall`.

**Repository renames.** Three of thirty repositories were renamed or
transferred during the window:

| ID (unchanged) | Was | Now |
|---|---|---|
| 64991887 | microsoft/LightGBM | lightgbm-org/LightGBM |
| 53548867 | dbt-labs/dbt-core | dbt-labs/dbt |
| 103071520 | great-expectations/great_expectations | fivetran/great_expectations |

All joins key on the numeric `repo_id`. Keyed on names, each would have
appeared as one project dying and another being born, and all three would have
surfaced as false positives on the at-risk list.

**Archived repository.** googleapis/python-bigquery is archived (last push
6 Mar 2026). It is still scored. The score does not read GitHub's `archived`
flag, so archived status is not shown on the dashboard. With no activity in the
last 90 days its response, unanswered, bug and retention components score a
neutral 0.5, and its maintainer activity ranks worst.

**Shorter windows.** Any repository whose backfill was narrowed because of API
rate limits would be listed here, because a shorter history shows fewer cohorts
and must not be read as declining community. None recorded at the time of
writing.

**Timezone.** The warehouse runs in UTC (`profiles.yml`). Without this, month
boundaries bucket differently on a laptop in IST than on a UTC CI runner — same
data, different numbers.

**The latest month.** Monthly charts exclude the current, partial month. The
GH Archive comparison also ends in August 2026, because the archive has no data
after that.

---

## Freshness

The pipeline is **not yet scheduled**. Today it is run by hand: `dbt build`,
then `scripts/to_sheets.py`, which publishes to the Google Sheet. A daily
GitHub Actions run is planned. It is not real-time.

- GraphQL is incremental from a per-repository watermark
- GH Archive is historical only (ADR 0002) and is not used for live metrics
- Scorecard updates weekly upstream
- Tableau Public refreshes a Google Sheets connection once every 24 hours —
  the ceiling of the free tier
- The time of the last publish is written to the `meta` sheet

---

## Sensitivity of the ranking

How far the ranking and the tiers move under the three weighting schemes is
computed by `scripts/sensitivity_analysis.py` and written to
`docs/sensitivity.csv` and `docs/sensitivity_summary.md`. Those files are
regenerated on every run, so the figures are kept there and not repeated here.

---

## Related decisions

- ADR 0001 — two ingestion sources after the October 2025 Events API change
- ADR 0002 — GH Archive demoted to historical source after fidelity collapse
- ADR 0003 — Scorecard via REST rather than BigQuery, on cost grounds