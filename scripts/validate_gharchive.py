"""Quantify the GH Archive fidelity gap against the authoritative GitHub API.

    python scripts/validate_gharchive.py
    python scripts/validate_gharchive.py --repo pandas-dev/pandas

For each month you backfilled, compares:
  archive_prs  - PullRequestEvent(opened) counted in data/raw/gharchive
  api_prs      - PRs actually opened that month, per the GitHub search API

Writes docs/gharchive_fidelity.csv. Chart that file and you have evidence for
the architecture decision rather than an assertion. Run it on two or three
repositories, not all thirty - the point is to establish the shape of the gap,
and the search API is rate-limited separately at 30 requests per minute.
"""
import argparse
import glob
import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seeds" / "repos.csv"
OUT = ROOT / "docs" / "gharchive_fidelity.csv"
SEARCH = "https://api.github.com/search/issues"

DEFAULT_REPOS = ["pandas-dev/pandas", "apache/airflow", "dbt-labs/dbt-core"]


def archive_counts(repo_id: int) -> pd.Series:
    files = glob.glob(str(ROOT / "data/raw/gharchive/**/*.parquet"), recursive=True)
    if not files:
        raise SystemExit("No GH Archive parquet found. Run scripts/pull_gharchive.py first.")
    df = pd.concat(pd.read_parquet(f) for f in files)
    df = df[(df.repo_id == repo_id) & (df.event_type == "PullRequestEvent")]
    df["month"] = pd.to_datetime(df.event_date).dt.to_period("M").astype(str)
    return df.groupby("month")["n"].sum()


def api_count(full_name: str, month: str, headers: dict) -> int:
    start = pd.Period(month).start_time.date()
    end = pd.Period(month).end_time.date()
    q = f"repo:{full_name} is:pr created:{start}..{end}"
    r = requests.get(SEARCH, params={"q": q, "per_page": 1}, headers=headers, timeout=30)
    r.raise_for_status()
    time.sleep(2.5)  # the search API allows ~30 requests/minute
    return r.json()["total_count"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", action="append", help="repeatable; defaults to three well-known repos")
    args = ap.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set in .env")
    headers = {"Authorization": f"Bearer {token}"}

    seed = pd.read_csv(SEED).dropna(subset=["repo_id"])
    targets = args.repo or DEFAULT_REPOS
    rows = []

    for full_name in targets:
        match = seed[seed.repo_full_name == full_name]
        if match.empty:
            print(f"skipping {full_name} - not in seeds/repos.csv")
            continue
        repo_id = int(match.iloc[0].repo_id)
        arch = archive_counts(repo_id)
        print(f"\n{full_name}")
        print(f"  {'month':<9} {'archive':>8} {'api':>8} {'captured':>9}")

        for month in sorted(arch.index):
            api = api_count(full_name, month, headers)
            got = int(arch[month])
            pct = round(100 * got / api, 1) if api else None
            rows.append({"repo": full_name, "month": month,
                         "archive_pr_events": got, "api_prs_opened": api,
                         "captured_pct": pct})
            print(f"  {month:<9} {got:>8} {api:>8} {str(pct) + '%':>9}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    print("Note: archive counts ALL PullRequestEvent actions (opened, closed,")
    print("reopened) while the API counts PRs opened, so early months can exceed")
    print("100%. The trend is the finding, not the absolute level.")


if __name__ == "__main__":
    main()