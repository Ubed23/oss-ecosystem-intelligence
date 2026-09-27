"""GitHub REST -> releases per repository.

    python scripts/pull_releases.py
    python scripts/pull_releases.py --repo pandas-dev/pandas --pages 1

Feeds two metrics:
  * release cadence      - median days between releases. A project that shipped
                           monthly for three years and has been silent for eight
                           is telling you something, especially alongside falling
                           merge activity.
  * regression ratio     - bugs opened in the 14 days after a release, against
                           the rate in the prior 90 days (section 11.5).

Drafts and prereleases are dropped: release candidates fire every few days and
would make a slowing project look healthy.

Output: data/raw/releases/dt=<date>/part-0.parquet  (full refresh each run -
releases are few and occasionally edited after publishing, so a full reload is
simpler and cheaper than incremental logic here.)
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
RAW = ROOT / "data" / "raw" / "releases"
API = "https://api.github.com/repos/{full_name}/releases"


def fetch_repo(full_name: str, headers: dict, max_pages: int) -> list[dict]:
    out = []
    for page in range(1, max_pages + 1):
        r = requests.get(API.format(full_name=full_name), headers=headers,
                         params={"per_page": 100, "page": page}, timeout=30)
        if r.status_code == 404:
            print(f"    404 - no releases endpoint")
            return out
        if r.status_code == 403:
            print(f"    rate limited, stopping this repo")
            return out
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        out += batch
        if len(batch) < 100:
            break            # last page
        time.sleep(0.3)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="only this repo")
    ap.add_argument("--pages", type=int, default=3,
                    help="max pages of 100 releases per repo (300 is plenty)")
    args = ap.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set in .env")
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}

    repos = pd.read_csv(SEED).dropna(subset=["repo_id"])
    if args.repo:
        repos = repos[repos.repo_full_name == args.repo]

    rows = []
    for _, repo in repos.iterrows():
        raw = fetch_repo(repo["repo_full_name"], headers, args.pages)
        kept = 0
        for rel in raw:
            if rel.get("draft") or rel.get("prerelease") or not rel.get("published_at"):
                continue
            rows.append({
                "repo_id": int(repo["repo_id"]),
                "repo_full_name": repo["repo_full_name"],
                "tag_name": rel.get("tag_name"),
                "release_name": rel.get("name"),
                "published_at": rel.get("published_at"),
            })
            kept += 1
        print(f"{repo['repo_full_name']:<45} {len(raw):>4} fetched, {kept:>4} kept")

    if not rows:
        raise SystemExit("No releases collected - check the token.")

    df = pd.DataFrame(rows)
    df["published_at"] = pd.to_datetime(df.published_at, utc=True)
    df = df.drop_duplicates(subset=["repo_id", "tag_name"])

    partition = datetime.now(timezone.utc).date().isoformat()
    out = RAW / f"dt={partition}" / "part-0.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\nsaved {len(df)} releases -> {out.relative_to(ROOT)}")

    # quick cadence preview - the real calculation lives in the dbt models
    cadence = (df.sort_values("published_at")
                 .groupby("repo_full_name")["published_at"]
                 .apply(lambda s: s.diff().dt.days.median())
                 .dropna().sort_values())
    print("\nmedian days between releases (fastest first):")
    print(cadence.head(8).round(1).to_string())
    print("...")
    print(cadence.tail(5).round(1).to_string())

    stale = df.groupby("repo_full_name")["published_at"].max()
    days = (pd.Timestamp.now(tz="UTC") - stale).dt.days.sort_values(ascending=False)
    print("\ndays since last release (quietest first):")
    print(days.head(8).to_string())


if __name__ == "__main__":
    main()