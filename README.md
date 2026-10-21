# Product Reliability & Developer Ecosystem Intelligence

**An open-source health scorecard for 30 widely used Python data and ML libraries.**
It answers one question: *which of the projects my product depends on are getting riskier, and how do I know?*

[![Dashboard](https://img.shields.io/badge/Tableau%20Public-live%20dashboard-1f77b4)](https://public.tableau.com/app/profile/ubed.m.a5650/viz/ProductReliabilityDeveloperEcosystemIntelligence)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Live dashboard:** <https://public.tableau.com/app/profile/ubed.m.a5650/viz/ProductReliabilityDeveloperEcosystemIntelligence>

![Executive overview](docs/images/01-executive-overview.png)

---

## Contents

1. [The problem](#1-the-problem)
2. [What the project delivers](#2-what-the-project-delivers)
3. [Architecture](#3-architecture)
4. [Data sources and why there are several](#4-data-sources-and-why-there-are-several)
5. [Data model and lineage](#5-data-model-and-lineage)
6. [The metrics](#6-the-metrics)
7. [The health score](#7-the-health-score)
8. [The dashboard](#8-the-dashboard)
9. [How I checked the work](#9-how-i-checked-the-work)
10. [Key findings](#10-key-findings)
11. [Design decisions](#11-design-decisions)
12. [Limitations](#12-limitations)
13. [Run it yourself](#13-run-it-yourself)
14. [Repository layout](#14-repository-layout)
15. [Roadmap: future development](#15-roadmap-future-development)

---

## 1. The problem

Every product built on open source inherits the risk of its dependencies. A library can look fine (many stars, recent release) while the people behind it quietly thin out: one maintainer merges nearly everything, issues wait weeks for an answer, newcomers do not come back.

Stars and download counts do not show this. This project measures **maintenance health** directly from how work actually flows through each repository: who merges, how fast people get answers, whether bugs pile up, whether new contributors stay.

The audience is a product, platform or engineering-management team deciding which dependencies deserve attention, funding or a contingency plan.

## 2. What the project delivers

| Deliverable | Where |
|---|---|
| A reproducible pipeline from raw GitHub data to analytics marts | `scripts/`, `models/` |
| A 0–100 health score per repository, monthly and current | `fct_health_score_monthly`, `fct_repo_health_current` |
| A multi-page Tableau Public dashboard | link above |
| A Google Sheet serving layer that refreshes the dashboard | `scripts/to_sheets.py` |
| Key Insights text generated from the data (24 sentences), so text and charts cannot disagree | `scripts/insights.py` |
| A weekly automated refresh: pull, test, publish | `.github/workflows/weekly-refresh.yml` |
| Validation: sensitivity analysis, backtest, source-fidelity check | `docs/` |
| Written decisions and metric definitions | `docs/decisions/`, `docs/metrics.md` |

## 3. Architecture

```mermaid
flowchart LR
    subgraph SRC["Sources"]
        GQL["GitHub GraphQL API<br/>issues, PRs, comments, reviews"]
        REST["GitHub REST API<br/>releases"]
        OSSF["OpenSSF Scorecard API"]
        BQ["GH Archive on BigQuery<br/>event history"]
    end

    subgraph ING["Ingestion (Python)"]
        P1["pull_github_graphql.py<br/>watermarks, rate-limit aware"]
        P2["pull_releases.py"]
        P3["pull_scorecard.py"]
        P4["pull_gharchive.py<br/>dry-run + byte cap"]
    P5["pull_open_issues.py<br/>one-off: every open issue"]
    end

    RAW[("Parquet files<br/>data/raw/")]

    subgraph WH["Transform: dbt + DuckDB"]
        STG["staging<br/>clean, dedupe, drop bots"]
        INT["intermediate<br/>bus factor, merged PRs,<br/>labelled issues, first contribution"]
        MART["marts<br/>facts and dimension"]
        TST["50 nodes in the build,<br/>including data tests"]
    end

    INS["insights.py<br/>24 generated sentences"]
    GHA["GitHub Actions<br/>weekly, Mondays 03:30 UTC"]
    SHEET[("Google Sheet<br/>oss-intel-marts")]
    TAB["Tableau Public<br/>daily sync from Sheet"]

    GQL --> P1 --> RAW
    REST --> P2 --> RAW
    OSSF --> P3 --> RAW
    BQ --> P4 --> RAW
    GQL --> P5 --> RAW
    RAW --> STG --> INT --> MART --> TST
    MART -->|"scripts/to_sheets.py"| SHEET --> TAB
    MART --> INS -->|"insights tab"| SHEET
    GHA -.->|"runs the pipeline"| P1
```

**Why this shape**

- **Parquet between ingestion and transformation.** Ingestion can be re-run or fixed without touching models, and the warehouse is rebuildable from files.
- **dbt + DuckDB.** Real SQL models, tests and lineage with no server to run. The whole warehouse is one file.
- **Google Sheets in the middle.** Tableau Public cannot hold a live database connection. Google Sheets is the one source it re-syncs automatically (every 24 hours), so the Sheet is the free-tier refresh path, not a workaround. Only small aggregates go up, never raw events.

## 4. Data sources and why there are several

| Source | Used for | Notes |
|---|---|---|
| **GitHub GraphQL** | Issues, pull requests, authors, labels, first maintainer response, contribution records | Primary source for every metric. Per-repo watermarks make runs resumable inside the 5,000-point hourly limit. |
| **GitHub REST** | Releases | Drafts and pre-releases are excluded. |
| **OpenSSF Scorecard (REST)** | Supply-chain security context (`scorecard_overall`, `check_maintained`) | Available for 26 of 30 repositories. Context only, not part of the score. |
| **GH Archive via BigQuery** | Pre-2026 history for the backtest; source-fidelity comparison | Queries are dry-run first and capped with `maximum_bytes_billed`. |

I started with GH Archive alone and had to change course. Two things broke that plan, both documented as decision records:

1. **GitHub changed the Events API payloads** (scheduled for 7 Oct 2025, per GitHub's changelog), removing fields such as commit lists and author association. GH Archive mirrors that API. → [ADR 0001](docs/decisions/0001-two-source-architecture.md)
2. **GH Archive fidelity collapsed in 2026.** Measured against the API, the archive's coverage fell by about 95%. → [ADR 0002](docs/decisions/0002-gharchive-fidelity.md)

So metrics come from the GraphQL API, and GH Archive is kept only where it still is reliable, and as evidence for the fidelity page.

![Source fidelity](docs/images/06-source-fidelity.png)

## 5. Data model and lineage

```mermaid
flowchart LR
    subgraph SEEDS["Seeds"]
        repos["repos"]
        bots["bots"]
        label_map["label_map"]
        score_weights["score_weights"]
    end

    subgraph STG["Staging (views)"]
        s1["stg_issues_prs"]
        s2["stg_contributions"]
        s3["stg_releases"]
        s4["stg_scorecard"]
        s5["stg_gharchive"]
    end

    subgraph INT["Intermediate"]
        i1["int_merged_prs"]
        i2["int_bus_factor"]
        i3["int_labeled_issues"]
        i4["int_first_contribution"]
        i5["int_maintainers"]
        i6["int_item_responses"]
        i7["int_bug_label_coverage"]
    end

    subgraph MARTS["Marts"]
        dim["dim_repo"]
        m1["fct_repo_health_monthly"]
        m2["fct_health_score_monthly"]
        m3["fct_repo_health_current"]
        m4["fct_contributor_cohorts"]
        m5["fct_release_reliability"]
        m6["fct_source_fidelity"]
    end

    bots --> s1 & s2 & s5
    s1 --> i1 --> i2
    s1 --> i3
    label_map --> i3
    s2 --> i4
    s1 --> i5 --> i6
    s1 --> i6
    i3 --> i7
    dim --> i7
    repos --> dim
    s4 --> dim

    i2 --> m1
    i1 --> m1
    i3 --> m1
    i6 --> m1
    s2 --> m1
    dim --> m1

    m1 --> m2
    i7 --> m2
    score_weights --> m2

    i4 --> m4
    s2 --> m4

    i3 --> m5
    s3 --> m5

    s1 --> m6
    s5 --> m6

    m1 --> m3
    i6 --> m3
    i7 --> m3
    m4 --> m3
    i1 --> m3
    s1 --> m3
    s3 --> m3
    dim --> m3
    score_weights --> m3
```

**Grain of each mart**

| Model | One row per | Purpose |
|---|---|---|
| `dim_repo` | repository | Names, ecosystem, criticality tier, Scorecard context |
| `fct_repo_health_monthly` | repository × month | All monthly raw metrics |
| `fct_health_score_monthly` | repository × month | Score history and 6-month change |
| `fct_repo_health_current` | repository | Latest snapshot, score and tier |
| `fct_contributor_cohorts` | repository × cohort month × months since | Retention triangle |
| `fct_release_reliability` | release | Bugs after vs. expected |
| `fct_source_fidelity` | month | GH Archive events vs. API items |

## 6. The metrics

Full definitions, null handling and caveats are in [`docs/metrics.md`](docs/metrics.md). In short:

| Metric | Definition | In score |
|---|---|---|
| **Bus factor** | Fewest authors whose merged PRs make up at least 50% of merged PRs | Yes |
| **Maintainer activity** | Distinct merged-PR authors, trailing 90 days | Yes |
| **Response time** | Time to first comment or review by a maintainer who is not the author. A maintainer is anyone who merged a PR in the repo or is labelled owner, member or collaborator ([ADR 0004](docs/decisions/0004-maintainer-identification.md)) | Yes |
| **Unanswered share** | Share of items older than 7 days, not opened by a maintainer, with no maintainer response within 7 days of creation | Yes |
| **Bug backlog** | Open bug issues at month end (labels normalised through `label_map`). Scored only where at least 10% of a repo's issues carry a bug label, otherwise neutral 0.5 | Yes |
| **Contributor retention** | Share of a first-time-contributor cohort active again in month 3 (pooled, used only when the sample is at least 100 people) | Yes |
| **Post-release regression ratio** | Bugs in the 14 days after a release vs. the 90-day baseline; judged only when at least 2 were expected and the window is complete | No (release page) |
| **Release cadence** | Median gap between releases, days since last release | No (context) |

Details worth knowing:

- Bots are removed at source (`seeds/bots.csv` plus a login heuristic).
- A contribution is **work**: opening an issue or PR, commenting, or reviewing. Stars and forks are interest, not work, and are excluded.
- Retention is a left-truncated cohort triangle that measures *activity in month N*, not survival. The current partial month and the first month of data (everyone active in Oct 2025, not only newcomers) are excluded.

![Contributor retention](docs/images/04-contributor-sustainability.png)

## 7. The health score

```mermaid
flowchart TD
    A["Six component metrics<br/>per repository"] --> B["Percentile rank<br/>within the 30 tracked repos<br/>(higher = healthier)"]
    B --> C{"Metric has<br/>no data?"}
    C -- yes --> D["Neutral 0.5<br/>(neither rewarded nor punished)"]
    C -- no --> E["Use the rank"]
    D --> F["Weighted sum<br/>seeds/score_weights.csv"]
    E --> F
    F --> G["Health score 0 to 100"]
    G --> H["Quartile tier by ntile 4:<br/>Critical, At Risk, Stable, Healthy"]
```

Design choices, each deliberate:

- **Percentile rank, not absolute thresholds.** There is no universal "good" bus factor for a data library. Ranking says how a project compares with its peers.
- **Neutral 0.5 for missing data.** A repo with no bugs filed, or too small a cohort for retention, is not penalised for having nothing to measure.
- **Three weight schemes live in a seed file** so weighting is configuration, not code, and can be stress-tested (next section).
- **Tiers are quartiles**, so by construction the split is always about 8 / 8 / 7 / 7. A tier is a *relative* label. It does not mean a quarter of projects are objectively failing.

![Health score dashboard](docs/images/08-health-score.png)

*How each repository's score is built from the six components, with adjustable weights and the shift against the balanced weighting. Scores are ranks among the 30 repositories, so read them as relative standing.*

## 8. The dashboard

Built in Tableau Public from the Google Sheet. Fixed-size pages, consistent navigation, and a Data Sources & Methodology page inside the workbook itself.

| Page | Question it answers | Screenshot |
|---|---|---|
| Executive Overview | Where does each repo stand, and who is moving? | `docs/images/01-executive-overview.png` |
| Health Score | How does each repo score, and how has it moved over 6 months? | `docs/images/08-health-score.png` |
| Maintainer & Risk | Where is maintainership concentrated? | `docs/images/02-maintainer-risk.png` |
| Engineering Operations | How work flows through each repo? | `docs/images/09-engineering-operations.png`|
| Bug Backlog | Which projects are accumulating open bugs? | `docs/images/03-bug-backlog.png` |
| Contributor Sustainability | Do new contributors stay? | `docs/images/04-contributor-sustainability.png` |
| Releases & Quality | Do releases precede a bug spike? | `docs/images/05-release-reliability.png` |
| Data Source Validation | Can the underlying data be trusted? | `docs/images/06-source-fidelity.png` |

**Key Insights are generated, not typed.** Each page has four insight cards. `scripts/insights.py` reads the same marts as the charts, fills sentence templates with computed numbers and `to_sheets.py` publishes them as the `insights` tab (24 rows: `page`, `ord`, `headline`, `text`). Tableau shows them in small worksheets filtered by page and order. The wording only describes numbers, never causes; direction words (rose, fell, broadly flat) come from a 5% threshold; the partial latest month is dropped. Typed text had gone stale, which is why this exists.

![Maintainer and risk](docs/images/02-maintainer-risk.png)

![Bug backlog](docs/images/03-bug-backlog.png)

![Release reliability](docs/images/05-release-reliability.png)

![Engineering operations](docs/images/09-engineering-operations.png)

## 9. How I checked the work

A composite score invites the objection "your weights are arbitrary". Instead of defending the weights I tested them.

### 9.1 Sensitivity analysis (`scripts/sensitivity_analysis.py`)

The score is recomputed under all three weight schemes. Results from the current build:

| Check | Result |
|---|---|
| Spearman rank correlation between the schemes | 0.899 (balanced vs reliability), 0.919 (balanced vs community), 0.716 (reliability vs community) |
| Repos keeping the same quartile tier under all three | **40%** (12 of 30) |
| Critical under **every** weighting | **dask**, **pydantic**, **ibis**, **python-bigquery** |

**Reading:** the ranking moves materially with the weights (the reliability and community schemes agree least, at 0.716), and fewer than half the repositories keep the same tier. The score is therefore one input and not a verdict. That is why the dashboard exposes the weights as parameters and calls out only the findings that survive every weighting. Full output: [`docs/sensitivity_summary.md`](docs/sensitivity_summary.md).

### 9.2 Backtest (`scripts/backtest.py`, [`docs/backtest_summary.md`](docs/backtest_summary.md))

Using only data up to 2024-12-31, flag repositories with deteriorating activity, then see which were later abandoned.

| | |
|---|---|
| Repositories | 243 |
| Later died | 4 (1.6%) |
| Flagged | 61 (2 died, 59 survived) |
| Precision / recall | 3.3% / 50.0% |
| Lift vs. base rate | about 2x |
| Median lead time | 10.9 months |

This is a **proof of concept, not a predictor.** Four events is far too few to claim skill, the model is activity-only, and "death" is a proxy. It shows the signal points the right way and nothing more.

### 9.3 Source-fidelity check

Comparing GH Archive events with API items per month showed the archive-to-API ratio falling from about 3.9 to about 0.16, which is why GH Archive was demoted (ADR 0002).

### 9.4 Automated tests

`dbt build` runs **50 nodes with 0 failures** (seeds, models and tests), including singular tests such as `assert_cohort_grid_valid`, `assert_weights_sum_to_one` and `assert_tiers_are_quartiles`.

## 10. Key findings

> These are the statements that held up under the checks above. Anything that depended on a particular weighting is deliberately left out.

- **dask, pydantic, ibis and python-bigquery rank in the bottom tier under every weighting** tested. pydantic is a clear case (bus factor 1, so one author accounts for the largest share of merged PRs). Treat the others as candidates to investigate rather than verdicts: a low score can partly reflect how maintainers are recognised, or, for python-bigquery, a repository that is winding down.
- **Maintainership is concentrated.** Half the tracked repositories (15 of 30) have a bus factor of 2 or less, and four (requests, pydantic, seaborn and prefect) have a bus factor of 1 (see Maintainer & Risk).
- **Retention is low everywhere.** Month-3 retention in the pooled cohorts is in the low single digits to roughly ten percent, so the score uses it as a *relative* signal.
- **Public event archives are not safe as a sole source.** The fidelity collapse and the 2025 payload change both silently corrupt metrics unless you measure the source against a second one.

## 11. Design decisions

| ADR | Decision |
|---|---|
| [0001](docs/decisions/0001-two-source-architecture.md) | Two sources: the API for authorship, merge, labels and responses; GH Archive for breadth and history |
| [0002](docs/decisions/0002-gharchive-fidelity.md) | Demote GH Archive after measured fidelity collapse |
| [0004](docs/decisions/0004-maintainer-identification.md) | Identify maintainers by merged pull requests, not only GitHub's label |
| [0003](docs/decisions/0003-scorecard-source.md) | Read OpenSSF Scorecard through the REST API (26 of 30 repos covered) instead of scanning the BigQuery table (85 GB per scan) |

## 12. Limitations

I would rather state these than have a reviewer find them.

- **Size bias.** Larger, busier repositories look more concentrated and more loaded simply because they have more traffic.
- **Maintainer identification.** A maintainer is anyone who merged a pull request in the repo or is labelled owner, member or collaborator (ADR 0004). All 30 repositories were re-pulled with the merger identity and the raw list of first responders, so the rule applies throughout. It still cannot recognise a maintainer who answers threads but has never merged a pull request.
- **Open-bug backlog.** The normal pull fetches items updated since 1 Oct 2025, so `pull_open_issues.py` adds every older issue that is still open (22,128 older open issues loaded, against 28,055 open in total). With them, open bugs across the 30 repositories fell about 20% (9,997 in Oct 2025 to 7,968 in Sep 2026), far less than the first, incomplete pull suggested. The backlog is scored only for repositories where at least 10% of issues carry a bug label.
- **Unanswered share** means: no maintainer response within 7 days, for items older than 7 days and not opened by a maintainer. It is a proxy for responsiveness, not a measure of it.
- **Tiers are quartiles.** They always split roughly 8 / 8 / 7 / 7 and are not absolute judgements.
- **Percentile ranking stretches small differences.** Retention values of about 1–10% become a full 0–1 spread.
- **Comment truncation.** Only the first 10 comments and 5 reviews per item are fetched; a late first maintainer reply on a very long thread could be missed. `comments_total` is stored so the truncation rate can be measured.
- **Retention is left-truncated** and measures activity, not survival.
- **Bug labels.** Counts depend on each project's labelling. Repos where under 10% of issues carry a bug label (duckdb, requests, seaborn, xgboost, matplotlib, python-bigquery) get a neutral backlog score instead of a good one, but their counts are still not comparable with other projects'.
- **Direct pushes are invisible.** Work committed without a PR is not seen.
- **Refresh is weekly, not live.** GitHub Actions refreshes the data every Monday and Tableau Public re-reads the Sheet about once a day, so the dashboard can be up to about a week old. Older open issues are re-pulled only by a manual run.
- **Criticality tier is a judgement label.** I assigned tier_1 (11 repositories), tier_2 (12) and tier_3 (7) by how much is built on a library and how hard it is to replace. It is not computed and not part of the health score; replacing it with a measured value such as dependent-package counts is a next step.
- **Public data only.** No internal incident, dependency-usage or revenue data.

## 13. Run it yourself

Requirements: Python 3.12, a GitHub token, optionally a Google Cloud project and service account.

```bash
git clone https://github.com/Ubed23/oss-ecosystem-intelligence.git
cd oss-ecosystem-intelligence

python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# macOS/Linux:         source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in the values
mkdir warehouse             # git-ignored, must exist before dbt runs
```

**Build the warehouse from Parquet and run all tests**

```bash
dbt build --profiles-dir . --threads 1
```

On Windows, if numerical libraries misbehave, set `$env:OPENBLAS_NUM_THREADS="1"` first.

**Refresh data**

```bash
python scripts/pull_github_graphql.py --since 2025-10-01   # backfill, resumable
python scripts/pull_github_graphql.py                      # daily increment
python scripts/pull_open_issues.py                        # one-off: every older issue still open
python scripts/pull_releases.py
python scripts/pull_scorecard.py
```

**Validate**

```bash
python scripts/sensitivity_analysis.py
```

**Publish to the Sheet that feeds Tableau**

```bash
python scripts/to_sheets.py --dry-run
python scripts/to_sheets.py
```

Share the Sheet with the service account's `client_email` as Editor, or you will get an error that looks like authentication but is permissions.

**Secrets:** `.env` and `service_account.json` are git-ignored. Never commit them.

**Weekly automation (GitHub Actions)**

`.github/workflows/weekly-refresh.yml` runs every Monday at 03:30 UTC and can also be started by hand from the Actions tab. It pulls new data, runs `dbt build` (the run stops if any of the 50 nodes fail), publishes to the Sheet, then commits the new raw data and watermarks back to the repo.

Set up once in the repository's Settings:

| Secret | Value |
|---|---|
| `GH_PAT` | A personal access token (the built-in token has a lower GraphQL limit) |
| `GSHEET_ID` | The ID in the Sheet's URL, between `/d/` and `/edit` |
| `GCP_SERVICE_ACCOUNT_JSON` | The full contents of `service_account.json` |

Also set Settings, Actions, General, Workflow permissions to Read and write. Because the job commits to `main`, run `git pull` before your next push. To re-pull older open issues, start the workflow by hand and tick the option.

**Print the Key Insights locally**

```bash
python scripts/insights.py
```

## 14. Repository layout

```
.
├── README.md
├── LICENSE
├── .env.example
├── dbt_project.yml / profiles.yml
├── requirements.txt
├── seeds/                  repos, bots, label_map, score_weights
├── models/
│   ├── staging/            stg_*   (clean, dedupe, drop bots)
│   ├── intermediate/       int_*   (bus factor, merged PRs, labelled issues, first contribution)
│   └── marts/              dim_repo, fct_*   (what Tableau reads)
├── tests/                  singular data tests
├── macros/                 as_of() - the fixed reference date for every window
├── scripts/                ingestion, backtest, sensitivity, insights, to_sheets
├── docs/
│   ├── metrics.md          every definition and caveat
│   ├── backtest_summary.md
│   ├── sensitivity_summary.md
│   ├── decisions/          ADRs
│   └── images/             dashboard screenshots
├── data/raw/               Parquet snapshots (committed so a fresh clone can build)
├── warehouse/              DuckDB file (git-ignored)
└── .github/workflows/      pipeline-check, weekly-refresh
```

## 15. Roadmap: future development

Grouped by theme and ordered roughly by value for effort. Nothing below is built yet, except where stated; the weekly pipeline and the generated Key Insights are done and described in sections 8 and 13.

```mermaid
flowchart LR
    N["Now<br/>weekly refresh,<br/>generated insights,<br/>30 repos"] --> A["Next<br/>correctness fixes,<br/>CI that builds,<br/>failure alerts"]
    A --> B["Later<br/>more repos,<br/>alerts, richer signals,<br/>forecasting"]
    B --> C["With internal data<br/>dependency-weighted<br/>risk and incident link"]
```

### 15.1 Next: correctness and reliability

| Item | Why it matters |
|---|---|
| Handle deleted ("ghost") authors explicitly | 89 of about 111,000 pulled items have no author and are dropped |
| Declare `sources.yml` for the raw Parquet files | Makes lineage and freshness checks complete |
| Measure and, where needed, paginate comment truncation using `comments_total` | Avoids missing a late first maintainer reply |

### 15.2 Next: automation

- **Done: weekly pipeline** in GitHub Actions (pull, `dbt build`, `to_sheets.py`, commit), with the token and service account stored as repository secrets.
- **CI that runs `dbt build`** on every pull request, not only an import check, so a broken model cannot reach `main`.
- **Data freshness check** that fails loudly if the newest ingested date is older than a threshold.
- **Failure notification** (email or Slack) when a scheduled run fails or a data test fails.
- **Branch protection** on `main` so changes go through pull requests.

### 15.3 Later: scope and signals

| Idea | Value |
|---|---|
| Expand beyond 30 repositories (JavaScript, Rust, Go ecosystems) | Tests whether the score generalises |
| Size-normalised metrics (per active contributor, per 100 items) | Reduces the size bias listed in the limitations |
| Absolute thresholds beside percentile ranks | A tier that means something on its own, not just relative standing |
| Tier labels with hysteresis | Stops repositories flickering across a quartile boundary month to month |
| Richer signals: CI pass rate, time to merge, time to close, security-advisory response time, dependency freshness | A fuller picture of reliability |
| Add Scorecard checks (e.g. code review, branch protection) into the score once coverage improves | Joins security posture to maintenance health |
| Maintainer-succession view: who else is close to taking over the merge load | Turns bus factor from a number into an action |
| Separate funding and governance context (foundation backed, sponsors, company backed) | Explains *why* some projects stay healthy |
| Migrate the serving layer from Sheets to a warehouse (BigQuery or MotherDuck) with a BI tool that supports live connections | Removes the 24-hour sync and cell-count limits |

### 15.4 Later: analytics and modelling

- **Early-warning alerts:** notify when a repository drops a tier or its score falls by more than a set amount over 6 months.
- **Trend forecasting:** simple time-series projection of score and bus factor to estimate time-to-critical.
- **A stronger backtest:** more repositories and more failure events, a proper train/test split, and multiple abandonment definitions (archived, no release for 12+ months, maintainer announcement).
- **Survival-style retention analysis** (true survival curves instead of activity-in-month-N), with confidence intervals on small cohorts.
- **Uncertainty on the score:** bootstrap intervals so close rankings are shown as ties rather than false precision.
- **Release risk model:** test whether post-release regression ratio predicts later bug spikes beyond chance.
- **Text signals (experimental):** classify issue and discussion tone or "maintainer burnout" language from public threads.

### 15.5 Later: product and presentation

- Per-repository drill-down page (one repo, all metrics, history, peers).
- A "compare two libraries" view for dependency-choice decisions.
- Parameter controls so a viewer can set their own weights (the component scores are already published for this).
- A short public write-up of the method and findings.
- Exportable one-page risk brief per repository.

### 15.6 With internal data

This is where the project becomes decision-grade for a real product team:

- Join **dependency usage** (which services import which library, and how deeply) so risk is weighted by blast radius.
- Join **incident and bug history** to learn which upstream signals actually preceded your own outages.
- Add **contribution back** (patches your team sent upstream) and **fork or vendoring** status.
- Produce a **prioritised watch list** with owners and a recommended action: monitor, contribute, pin a version, or plan a migration.

## License

[MIT](LICENSE)