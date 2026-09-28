"""Backtest: would this model have flagged projects that later died?

Three stages, run in order:

    python scripts/backtest.py find                    # build the candidate set
    python scripts/backtest.py pull --dry-run          # check the BigQuery cost
    python scripts/backtest.py pull
    python scripts/backtest.py score

The design is a standard fixed-observation backtest:

    OBSERVATION DATE T0 = 2024-12-31
    features  : activity in the 12 months BEFORE T0
    label     : did the project die in the 12 months AFTER T0?
    prediction: bottom quartile of the activity score at T0

This avoids the trap of scoring each project at its own private date, which
leaks the outcome into the feature window.

Two deliberate limitations, both stated in the README rather than hidden:

  1. ACTIVITY METRICS ONLY. Response times, merge status and labels cannot be
     reconstructed for 2024 - GitHub stripped them from event payloads in
     October 2025 (ADR 0001). The backtest therefore tests a weaker model than
     the live one, which makes its results a floor, not a ceiling.
  2. DEATH IS A PROXY. GitHub exposes an `archived` flag but not a reliable
     archival date, so "died" means archived now, or no push for 12+ months.
     Dormancy is not the same as archival, and both are reported separately.
"""
import argparse
import json
import os
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "seeds" / "backtest_repos.csv"
ACT = ROOT / "data" / "raw" / "backtest_activity"
OUT_CSV = ROOT / "docs" / "backtest.csv"
OUT_MD = ROOT / "docs" / "backtest_summary.md"

T0 = date(2024, 12, 31)
FEATURE_START = date(2024, 1, 1)
DORMANT_MONTHS = 12
GB = 1024 ** 3

TOP_LIST = ("https://raw.githubusercontent.com/hugovk/top-pypi-packages/"
            "main/top-pypi-packages.json")
PYPI = "https://pypi.org/pypi/{pkg}/json"
GH_RE = re.compile(r"github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)", re.I)

QUERY = """
SELECT
  DATE_TRUNC(DATE(created_at), MONTH) AS month_start,
  repo.id                             AS repo_id,
  actor.login                         AS actor,
  type                                AS event_type,
  COUNT(*)                            AS n
FROM `githubarchive.day.20*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
  AND repo.id IN UNNEST(@repo_ids)
GROUP BY 1, 2, 3, 4
"""


# ---------------------------------------------------------------- find
def github_repo(info: dict) -> str | None:
    urls = dict(info.get("project_urls") or {})
    ordered = [v for k, v in urls.items()
               if any(w in k.lower() for w in ("source", "repo", "code", "github"))]
    ordered += list(urls.values()) + [info.get("home_page") or ""]
    for url in ordered:
        m = GH_RE.search(url or "")
        if m:
            return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
    return None


def cmd_find(args) -> None:
    """Candidate universe: top PyPI packages, labelled alive or dead."""
    token = os.environ["GITHUB_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    print("downloading top-PyPI-packages ...")
    pkgs = [r["project"] for r in requests.get(TOP_LIST, timeout=60).json()["rows"][: args.top]]

    rows, seen = [], set()
    for i, pkg in enumerate(pkgs, 1):
        try:
            info = requests.get(PYPI.format(pkg=pkg), timeout=30).json()["info"]
        except Exception:
            continue
        full = github_repo(info)
        if not full or full.lower() in seen:
            continue
        seen.add(full.lower())

        r = requests.get(f"https://api.github.com/repos/{full}", headers=headers, timeout=30)
        if r.status_code != 200:
            continue
        b = r.json()
        pushed = pd.Timestamp(b["pushed_at"]).tz_convert(None).date()
        months_idle = (date.today() - pushed).days / 30.4
        rows.append({
            "repo_full_name": b["full_name"],
            "repo_id": b["id"],
            "package_name": pkg,
            "archived": b["archived"],
            "last_push": pushed.isoformat(),
            "months_since_push": round(months_idle, 1),
            # died = archived, or silent for a year or more
            "died": bool(b["archived"]) or months_idle >= DORMANT_MONTHS,
        })
        if i % 25 == 0:
            print(f"  {i}/{len(pkgs)} inspected, {len(rows)} resolved")
        time.sleep(0.2)

    df = pd.DataFrame(rows)
    CAND.parent.mkdir(exist_ok=True)
    df.to_csv(CAND, index=False)
    print(f"\nwrote {CAND.relative_to(ROOT)}: {len(df)} repositories, "
          f"{df.died.sum()} labelled dead ({df.archived.sum()} archived, "
          f"{(df.died & ~df.archived).sum()} dormant)")
    if df.died.sum() < 8:
        print("WARNING: too few dead repositories for a meaningful backtest.")
        print("Re-run with a larger --top, or widen the dormancy threshold.")


# ---------------------------------------------------------------- pull
def cmd_pull(args) -> None:
    from google.cloud import bigquery

    ids = pd.read_csv(CAND).repo_id.dropna().astype("int64").tolist()
    print(f"{len(ids)} candidate repositories")
    client = bigquery.Client(project=os.environ["BQ_PROJECT"])

    months = pd.period_range(FEATURE_START, T0, freq="M")
    for m in months:
        part = ACT / f"dt={m}" / "part-0.parquet"
        if part.exists() and not args.overwrite:
            print(f"[{m}] already on disk")
            continue
        start, end = m.start_time.date(), m.end_time.date()
        params = [
            bigquery.ScalarQueryParameter("start_suffix", "STRING", start.strftime("%y%m%d")),
            bigquery.ScalarQueryParameter("end_suffix", "STRING", end.strftime("%y%m%d")),
            bigquery.ArrayQueryParameter("repo_ids", "INT64", ids),
        ]
        dry = client.query(QUERY, bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, query_parameters=params))
        gb = dry.total_bytes_processed / GB
        print(f"[{m}] estimate {gb:,.1f} GB", end="")
        if gb > args.budget_gb:
            print("  ABORT: over budget"); return
        if args.dry_run:
            print("  (dry run)"); continue

        job = client.query(QUERY, bigquery.QueryJobConfig(
            query_parameters=params, maximum_bytes_billed=int(args.budget_gb * GB)))
        df = job.to_dataframe()
        df["month_start"] = pd.to_datetime(df["month_start"])
        df["repo_id"] = df.repo_id.astype("int64")
        part.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(part, index=False)
        print(f"  -> {len(df):,} rows")


# ---------------------------------------------------------------- score
def cmd_score(args) -> None:
    import glob
    files = glob.glob(str(ACT / "**" / "*.parquet"), recursive=True)
    if not files:
        raise SystemExit("No backtest activity found. Run: backtest.py pull")

    act = pd.concat(pd.read_parquet(f) for f in files)
    act = act[~act.actor.str.contains(r"\[bot\]", na=False)]
    cand = pd.read_csv(CAND)

    # --- features from the 12 months before T0 only ---
    monthly = (act.groupby(["repo_id", "month_start"])
                  .agg(events=("n", "sum"), actors=("actor", "nunique"))
                  .reset_index())

    feat = (monthly.groupby("repo_id")
            .agg(total_events=("events", "sum"),
                 avg_actors=("actors", "mean"),
                 active_months=("month_start", "nunique"))
            .reset_index())

    # concentration: share of activity from the single busiest contributor
    top = (act.groupby(["repo_id", "actor"]).n.sum().reset_index()
              .sort_values("n", ascending=False)
              .groupby("repo_id").head(1)
              .rename(columns={"n": "top_actor_events"})[["repo_id", "top_actor_events"]])
    feat = feat.merge(top, on="repo_id", how="left")
    feat["top_actor_share"] = feat.top_actor_events / feat.total_events

    # trend: second half of the window against the first
    half = pd.Timestamp("2024-07-01")
    trend = (monthly.assign(late=monthly.month_start >= half)
                    .groupby(["repo_id", "late"]).events.sum().unstack(fill_value=0))
    trend.columns = ["events_h1", "events_h2"]
    trend["trend_ratio"] = trend.events_h2 / trend.events_h1.replace(0, pd.NA)
    feat = feat.merge(trend.reset_index(), on="repo_id", how="left")

    df = cand.merge(feat, on="repo_id", how="left").fillna({
        "total_events": 0, "avg_actors": 0, "active_months": 0,
        "top_actor_share": 1.0, "trend_ratio": 0.0})

    # Restrict to projects comparable to the tracked set. Micro-libraries that
    # implement a fixed spec stop receiving commits because they are FINISHED,
    # not abandoned - "died" is not a meaningful label for them, and they
    # dominate the top-PyPI list.
    before = len(df)
    df = df[(df.avg_actors >= 5) & (df.total_events >= 500)].copy()
    print(f"population: {len(df)} of {before} repositories "
          f"(filtered to avg_actors>=5 and total_events>=500)")

    # --- activity-only score, same shape as the live model ---
    df["s_events"] = df.total_events.rank(pct=True)
    df["s_actors"] = df.avg_actors.rank(pct=True)
    df["s_months"] = df.active_months.rank(pct=True)
    df["s_concentration"] = (-df.top_actor_share).rank(pct=True)
    df["s_trend"] = df.trend_ratio.rank(pct=True)
    df["activity_score"] = 100 * (
        0.25 * df.s_events + 0.25 * df.s_actors + 0.20 * df.s_months
        + 0.15 * df.s_concentration + 0.15 * df.s_trend)

    df["flagged"] = df.activity_score <= df.activity_score.quantile(0.25)

    tp = int((df.flagged & df.died).sum())
    fp = int((df.flagged & ~df.died).sum())
    fn = int((~df.flagged & df.died).sum())
    tn = int((~df.flagged & ~df.died).sum())
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    base = df.died.mean()

    caught = df[df.flagged & df.died]
    lead = ((pd.to_datetime(caught.last_push) - pd.Timestamp(T0)).dt.days / 30.4)
    lead_months = round(lead.median(), 1) if len(caught) else float("nan")

    print(f"\nObservation date T0: {T0}   features: {FEATURE_START} to {T0}")
    print(f"Repositories: {len(df)}   died since: {int(df.died.sum())} "
          f"(base rate {base:.1%})\n")
    print("                 died   survived")
    print(f"  flagged     {tp:>6} {fp:>10}")
    print(f"  not flagged {fn:>6} {tn:>10}\n")
    print(f"  precision {precision:.1%}  - of those flagged, this share died")
    print(f"  recall    {recall:.1%}  - of those that died, this share was flagged")
    print(f"  lift      {precision / base:.2f}x over the base rate")
    print(f"  median lead time: {lead_months} months from T0 to last push\n")

    print("Correctly flagged:")
    print(caught.nsmallest(10, "activity_score")[
        ["repo_full_name", "activity_score", "archived", "months_since_push"]
    ].round(1).to_string(index=False))

    print("\nMissed (died but not flagged) - worth understanding:")
    print(df[~df.flagged & df.died].nsmallest(5, "activity_score")[
        ["repo_full_name", "activity_score", "total_events", "avg_actors"]
    ].round(1).to_string(index=False))

    OUT_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    OUT_MD.write_text("\n".join([
        "# Backtest", "",
        f"**Observation date** {T0}. Features from activity in "
        f"{FEATURE_START} to {T0}. Label: archived, or no push for "
        f"{DORMANT_MONTHS}+ months, as of today.", "",
        f"- Repositories: **{len(df)}**",
        f"- Died since T0: **{int(df.died.sum())}** (base rate {base:.1%})",
        f"- Flagged (bottom quartile of activity score): **{int(df.flagged.sum())}**", "",
        "| | died | survived |", "|---|---|---|",
        f"| flagged | {tp} | {fp} |", f"| not flagged | {fn} | {tn} |", "",
        f"- **Precision {precision:.1%}** - of repositories flagged, this share died",
        f"- **Recall {recall:.1%}** - of repositories that died, this share was flagged",
        f"- **Lift {precision / base:.2f}x** over the {base:.1%} base rate",
        f"- **Median lead time {lead_months} months**", "",
        "## Limitations", "",
        "1. Activity metrics only. Response times, merge status and labels cannot be",
        "   reconstructed for 2024 because GitHub stripped those fields from event",
        "   payloads in October 2025. The live model uses more signal than this test,",
        "   so these numbers are a floor rather than a ceiling.",
        "2. Death is a proxy: archived now, or silent for 12+ months. Dormancy is not",
        "   archival, and the two are counted separately in `docs/backtest.csv`.",
        "3. Survivorship: the candidate set comes from currently-listed PyPI packages,",
        "   so packages deleted outright are absent.",
    ]), encoding="utf-8")
    print(f"\nwrote {OUT_CSV.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="build the labelled candidate set")
    f.add_argument("--top", type=int, default=600)
    f.set_defaults(func=cmd_find)

    p = sub.add_parser("pull", help="fetch 2024 activity from GH Archive")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--budget-gb", type=float, default=60.0)
    p.set_defaults(func=cmd_pull)

    s = sub.add_parser("score", help="score, compare against outcomes, write the report")
    s.set_defaults(func=cmd_score)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()