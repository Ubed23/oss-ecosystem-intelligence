"""Pull daily activity counts from GH Archive (public BigQuery dataset).

    python scripts/pull_gharchive.py --month 2025-10 --dry-run   # estimate only
    python scripts/pull_gharchive.py --month 2025-10             # run it
    python scripts/pull_gharchive.py --from 2025-10 --to 2026-09 # whole backfill
    python scripts/pull_gharchive.py --daily                     # incremental, D-2

Cost control is the point of this file:
  * BigQuery bills by COLUMNS SCANNED. Never SELECT *.
  * Only _TABLE_SUFFIX (the date range) and the column list reduce bytes.
    Filtering on repo.id does NOT - the tables are not clustered.
  * Every query is dry-run first; anything over the budget aborts.
  * maximum_bytes_billed is a second guard enforced by BigQuery itself.

Output: data/raw/gharchive/dt=<partition>/part-0.parquet
One partition per month (backfill) or per day (incremental). Re-running a
period overwrites its own partition, so the script is safe to repeat.
"""
import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seeds" / "repos.csv"
RAW = ROOT / "data" / "raw" / "gharchive"
GB = 1024 ** 3

QUERY = """
SELECT
  DATE(created_at)  AS event_date,
  repo.id           AS repo_id,
  actor.login       AS actor,
  type              AS event_type,
  COUNT(*)          AS n
FROM `githubarchive.day.20*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
  AND repo.id IN UNNEST(@repo_ids)
GROUP BY 1, 2, 3, 4
"""


def repo_ids() -> list[int]:
    df = pd.read_csv(SEED)
    ids = df["repo_id"].dropna().astype("int64").tolist()
    if not ids:
        raise SystemExit("seeds/repos.csv has no repo_id values. "
                         "Run scripts/resolve_repo_ids.py first.")
    print(f"tracking {len(ids)} repositories")
    return ids


def month_bounds(month: str) -> tuple[date, date]:
    """'2025-10' -> (2025-10-01, 2025-10-31)"""
    y, m = (int(x) for x in month.split("-"))
    first = date(y, m, 1)
    last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return first, last


def months_between(start: str, end: str) -> list[str]:
    y1, m1 = (int(x) for x in start.split("-"))
    y2, m2 = (int(x) for x in end.split("-"))
    out = []
    while (y1, m1) <= (y2, m2):
        out.append(f"{y1:04d}-{m1:02d}")
        y1, m1 = (y1 + (m1 == 12), (m1 % 12) + 1)
    return out


def run_period(client, ids, start: date, end: date, partition: str,
               budget_gb: float, dry_only: bool) -> None:
    out_path = RAW / f"dt={partition}" / "part-0.parquet"

    params = [
        bigquery.ScalarQueryParameter("start_suffix", "STRING", start.strftime("%y%m%d")),
        bigquery.ScalarQueryParameter("end_suffix", "STRING", end.strftime("%y%m%d")),
        bigquery.ArrayQueryParameter("repo_ids", "INT64", ids),
    ]

    # --- dry run: free, instant, tells you what the real query would cost ---
    dry = client.query(QUERY, bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False, query_parameters=params))
    gb = dry.total_bytes_processed / GB
    print(f"[{partition}] {start} .. {end} -> estimate {gb:,.1f} GB", end="")

    if gb > budget_gb:
        print(f"\n  ABORT: {gb:,.1f} GB exceeds the {budget_gb} GB budget for one run.")
        print("  Narrow the period, or raise --budget-gb if you know you can afford it.")
        return
    if dry_only:
        print("  (dry run only)")
        return

    # --- real query, with BigQuery's own byte ceiling as a second guard ---
    job = client.query(QUERY, bigquery.QueryJobConfig(
        query_parameters=params, maximum_bytes_billed=int(budget_gb * GB)))
    df = job.to_dataframe()
    df["event_date"] = pd.to_datetime(df["event_date"])   # dbdate -> plain datetime
    df["repo_id"] = df["repo_id"].astype("int64")
    df[["actor", "event_type"]] = df[["actor", "event_type"]].astype("string")
    billed = (job.total_bytes_billed or 0) / GB

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"  -> billed {billed:,.1f} GB, {len(df):,} rows, saved {out_path.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="single month, e.g. 2025-10")
    ap.add_argument("--from", dest="start", help="first month of a backfill")
    ap.add_argument("--to", dest="end", help="last month of a backfill")
    ap.add_argument("--daily", action="store_true",
                    help="incremental: one day, D-minus-lag")
    ap.add_argument("--lag-days", type=int, default=2,
                    help="GH Archive loads late; 2 is safe")
    ap.add_argument("--dry-run", action="store_true", help="estimate only, run nothing")
    ap.add_argument("--budget-gb", type=float,
                    default=float(os.getenv("BQ_MAX_GB_PER_RUN", 60)),
                    help="abort any single query above this")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip months already on disk (resume a broken backfill)")
    args = ap.parse_args()

    project = os.getenv("BQ_PROJECT")
    if not project:
        raise SystemExit("BQ_PROJECT is not set in .env")
    client = bigquery.Client(project=project)
    ids = repo_ids()

    if args.daily:
        day = date.today() - timedelta(days=args.lag_days)
        run_period(client, ids, day, day, day.isoformat(), args.budget_gb, args.dry_run)
        return

    if args.month:
        targets = [args.month]
    elif args.start and args.end:
        targets = months_between(args.start, args.end)
    else:
        raise SystemExit("Pass --month, or --from and --to, or --daily.")

    total = 0.0
    for m in targets:
        if args.skip_existing and (RAW / f"dt={m}" / "part-0.parquet").exists():
            print(f"[{m}] already on disk, skipping")
            continue
        first, last = month_bounds(m)
        run_period(client, ids, first, last, m, args.budget_gb, args.dry_run)
        total += 1

    print(f"\nprocessed {int(total)} period(s)")


if __name__ == "__main__":
    main()