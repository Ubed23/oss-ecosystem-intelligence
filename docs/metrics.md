# Metric definitions

Every metric is defined here before it is built. Where a definition is
contested, the argument is recorded rather than buried in SQL.

Scope: 30 repositories in the Python data and ML ecosystem.
Analysis window: from **2025-10-01**.
Refresh: daily, via GitHub Actions. Not real-time — see "Freshness" below.

---

## Sources and what each is trusted for

| Source | Used for | Trusted? |
|---|---|---|
| GitHub GraphQL API | Every live metric | Yes — authoritative |
| GitHub REST (releases) | Cadence, regression ratio | Yes |
| OpenSSF Scorecard | Independent cross-check | Yes, but partial coverage (26/30) |
| GH Archive (BigQuery) | Historical backtest only | **No** for recent data — see ADR 0002 |

---

## The metrics

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
concentrated.

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
Neither number means anything alone.

**Negative values.** One row in ~116,000 had a first response predating
creation. This happens when an issue is transferred between repositories
(comments survive, `createdAt` resets) or converted from a discussion. Recorded
as **null, not zero** — zero would read as "answered instantly", which is
better than any real value. When a value is impossible, record absence rather
than inventing a plausible number.

**Blind spot.** Replies outside GitHub — Slack, mailing lists, Discourse — are
not counted.

### Unresponded rate
Share of items with no maintainer response after **7 days**. Reported alongside
response time, never separately.

### Bug backlog
**Definition.** Count and age of open issues whose labels normalise to `bug` or
`regression`.

**Label normalisation.** Projects use different vocabularies — "bug",
"type: bug", "kind/bug", "defect". `seeds/label_map.csv` maps them. Unmapped
labels are **dropped, not guessed**.

**Blind spot.** A project that does not label bugs consistently scores
artificially well. Pair backlog with total open issues so a project cannot hide
by not labelling.

### Contributor retention (cohorts)
**Definition.** Of the people whose first observed contribution to a repository
fell in month M, what share contributed again 1, 3 and 6 months later?

**What counts as a contribution.** Opening an issue or PR, commenting,
reviewing. **Not** stars, forks or watches — those measure interest, not work,
and including them would let a viral tweet look like community growth.

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

**Null handling.** Null when the baseline window held no bugs — division
guarded, not faked.

### Release cadence
Median days between non-prerelease, non-draft releases. Prereleases are
excluded because release candidates fire every few days and would make a
slowing project look healthy.

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

**What the score therefore claims.** "Relative to these 30 repositories", not
"objectively healthy". That is the honest reading and it is the one printed on
the dashboard.

**Weights** live in `seeds/score_weights.csv` in three schemes (balanced,
reliability-heavy, community-heavy), never hard-coded. This makes the
sensitivity analysis a one-command job and lets the weights be exposed as
Tableau parameters so a viewer can change the priorities themselves.

**Tiers are quartiles, not fixed thresholds.** Fixed cutoffs (25/50/75) put 29
of 30 repositories in the middle two bands, because percentile-rank composites
cluster near the middle by construction. Quartiles of the tracked set mean
"critical" = bottom quartile relative to these 30, which matches what the score
actually measures.

**Trailing 90 days for the current snapshot.** Responsiveness and merge
activity use a trailing 90-day window, not the latest calendar month. A quiet
month would otherwise leave those metrics null, and a null percentile rank
would score the repository as worst — punishing "no data" as if it were "bad
data".

**Null direction is set per metric.** `bus_factor_50 nulls first` — no merged
PRs is genuinely concerning. `ttfr_p50_hours desc nulls last` — no issues
opened is not.

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

**Shorter windows.** Any repository whose backfill was narrowed because of API
rate limits is listed here, because a shorter history shows fewer cohorts and
must not be read as declining community.

| Repository | Window | Reason |
|---|---|---|
| _(record any here)_ | | |

**Timezone.** The warehouse runs in UTC (`profiles.yml`). Without this, month
boundaries bucket differently on a laptop in IST than on a UTC CI runner — same
data, different numbers.

---

## Freshness

The pipeline is **automated and daily**. It is not real-time.

- GH Archive processes D-2, because the archive loads with a lag
- GraphQL is incremental from a per-repository watermark
- Scorecard refreshes weekly, matching the upstream scan
- Tableau Public refreshes a Google Sheets connection once every 24 hours —
  the ceiling of the free tier

"Data as of" is displayed on every dashboard.

---

## Related decisions

- ADR 0001 — two ingestion sources after the October 2025 Events API change
- ADR 0002 — GH Archive demoted to historical source after fidelity collapse
- ADR 0003 — Scorecard via REST rather than BigQuery, on cost grounds