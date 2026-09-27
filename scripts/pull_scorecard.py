"""OpenSSF Scorecard -> an independent security-posture signal per repository.

    python scripts/pull_scorecard.py --dry-run
    python scripts/pull_scorecard.py
    python scripts/pull_scorecard.py --rest-only

Why this source: every other metric in the project is something I computed.
Scorecard is computed by someone else, with a different method. Where my health
score and their Maintained check disagree, that disagreement is a finding worth
a chart - and it stops the dashboard being one number marking its own homework.

Two ways to get it, and the order matters:

  1. BigQuery, `openssf.scorecardcron.scorecard-v2_latest`. OpenSSF runs a
     weekly scan of the million most critical open source projects and
     publishes it here. Broad coverage, one query.
  2. REST, api.securityscorecards.dev. Only returns projects that opted in by
     setting publish_results: true in the Scorecard GitHub Action, so many
     repositories legitimately 404. Used as a fallback for anything BigQuery
     missed.

Run weekly, not daily - the underlying scan is weekly.

Output: data/raw/scorecard/dt=<date>/part-0.parquet
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seeds" / "repos.csv"
RAW = ROOT / "data" / "raw" / "scorecard"
REST = "https://api.securityscorecards.dev/projects/github.com/{full_name}"
GB = 1024 ** 3

KEEP_CHECKS = ["Maintained", "Code-Review", "Vulnerabilities",
               "Dependency-Update-Tool", "Branch-Protection", "Fuzzing"]

BQ_QUERY = """
SELECT
  repo.name        AS repo_url,
  date             AS scorecard_date,
  score            AS scorecard_overall,
  ARRAY(SELECT AS STRUCT c.name, c.score FROM UNNEST(checks) c) AS checks
FROM `openssf.scorecardcron.scorecard-v2_latest`
WHERE repo.name IN UNNEST(@repo_urls)
"""


def from_bigquery(full_names: list[str], budget_gb: float, dry_only: bool) -> pd.DataFrame:
    from google.cloud import bigquery

    client = bigquery.Client(project=os.environ["BQ_PROJECT"])
    urls = [f"github.com/{n}" for n in full_names]
    params = [bigquery.ArrayQueryParameter("repo_urls", "STRING", urls)]

    dry = client.query(BQ_QUERY, bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False, query_parameters=params))
    gb = dry.total_bytes_processed / GB
    print(f"BigQuery dry run: {gb:,.2f} GB")
    if gb > budget_gb:
        print(f"  over the {budget_gb} GB budget - skipping BigQuery, using REST only")
        return pd.DataFrame()
    if dry_only:
        return pd.DataFrame()

    job = client.query(BQ_QUERY, bigquery.QueryJobConfig(
        query_parameters=params, maximum_bytes_billed=int(budget_gb * GB)))
    rows = []
    for r in job.result():
        checks = {c["name"]: c["score"] for c in r["checks"]}
        rows.append({
            "repo_full_name": r["repo_url"].removeprefix("github.com/"),
            "scorecard_date": r["scorecard_date"],
            "scorecard_overall": r["scorecard_overall"],
            "source": "bigquery",
            **{f"check_{c.lower().replace('-', '_')}": checks.get(c) for c in KEEP_CHECKS},
        })
    print(f"  BigQuery returned {len(rows)} repositories")
    return pd.DataFrame(rows)


def from_rest(full_name: str) -> dict | None:
    r = requests.get(REST.format(full_name=full_name), timeout=30)
    time.sleep(0.5)
    if r.status_code != 200:
        return None
    body = r.json()
    checks = {c["name"]: c.get("score") for c in body.get("checks", [])}
    return {
        "repo_full_name": full_name,
        "scorecard_date": body.get("date"),
        "scorecard_overall": body.get("score"),
        "source": "rest",
        **{f"check_{c.lower().replace('-', '_')}": checks.get(c) for c in KEEP_CHECKS},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rest-only", action="store_true",
                    help="skip BigQuery entirely")
    ap.add_argument("--budget-gb", type=float, default=5.0)
    args = ap.parse_args()

    seed = pd.read_csv(SEED).dropna(subset=["repo_id"])
    names = seed.repo_full_name.tolist()

    df = pd.DataFrame()
    if not args.rest_only:
        try:
            df = from_bigquery(names, args.budget_gb, args.dry_run)
        except Exception as exc:
            print(f"BigQuery path failed ({exc}); falling back to REST")

    if args.dry_run:
        return

    have = set(df.repo_full_name) if not df.empty else set()
    missing = [n for n in names if n not in have]
    print(f"\n{len(missing)} repositories not in BigQuery - trying REST")

    rest_rows = []
    for name in missing:
        row = from_rest(name)
        print(f"  {name:<45} {'score ' + str(row['scorecard_overall']) if row else 'no published scorecard'}")
        if row:
            rest_rows.append(row)

    df = pd.concat([df, pd.DataFrame(rest_rows)], ignore_index=True) if rest_rows else df
    if df.empty:
        raise SystemExit("No scorecard data from either source.")

    df = df.merge(seed[["repo_full_name", "repo_id"]], on="repo_full_name", how="left")
    df["repo_id"] = df.repo_id.astype("int64")
    df["scorecard_date"] = pd.to_datetime(df.scorecard_date, utc=True, errors="coerce")

    partition = datetime.now(timezone.utc).date().isoformat()
    out = RAW / f"dt={partition}" / "part-0.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    print(f"\nsaved {len(df)}/{len(names)} repositories -> {out.relative_to(ROOT)}")
    print(df.source.value_counts().to_string())
    print("\nlowest overall scores:")
    print(df.nsmallest(6, "scorecard_overall")[
        ["repo_full_name", "scorecard_overall", "check_maintained"]].to_string(index=False))


if __name__ == "__main__":
    main()