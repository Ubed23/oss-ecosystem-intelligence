"""One-off: pull EVERY currently open issue, however old.

Why this exists
    pull_github_graphql.py pages issues newest-updated first and stops at the
    watermark (1 Oct 2025). A bug that is still open but nobody has touched
    since then is never fetched, so the bug backlog (a STOCK of everything still
    open) came out too low.

What it does
    Fetches all OPEN issues created before the analysis start and saves them
    alongside the other raw issue data. Issues created inside the window are
    skipped: the normal pull already has them, with comments, and a lighter row
    here could replace a richer one during de-duplication.

Cost
    A light query (no comments). Roughly 100 issues per request, so tens of
    thousands of open issues across 30 repos is a few hundred requests.

Usage
    python scripts/pull_open_issues.py                       # all 30 repos
    python scripts/pull_open_issues.py --repo pandas-dev/pandas
    python scripts/pull_open_issues.py --before 2025-10-01   # default
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from pull_github_graphql import RAW, SEED, flatten_item, gql, ts

load_dotenv()

PAGE = 100
LOW_POINTS = 200

OPEN_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  rateLimit { remaining resetAt cost }
  repository(owner:$owner, name:$name) {
    issues(first:%d, after:$cursor, states:OPEN,
           orderBy:{field:CREATED_AT, direction:ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number createdAt updatedAt closedAt state
        author { login }
        authorAssociation
        labels(first: 20) { nodes { name } }
      }
    }
  }
}
""" % PAGE


def pull_repo(repo, token: str, before: datetime, deadline: float) -> tuple[list, bool, int]:
    """Return (rows, complete, open_total) for one repo."""
    owner, name = repo["repo_full_name"].split("/")
    repo_id = int(repo["repo_id"])
    cursor, rows, total = None, [], 0
    while True:
        if time.time() > deadline:
            return rows, False, total
        data = gql(OPEN_QUERY, {"owner": owner, "name": name, "cursor": cursor}, token)
        conn = data["repository"]["issues"]
        total = conn["totalCount"]
        for node in conn["nodes"]:
            # oldest first, so once we pass the window start everything after is
            # already covered by the normal pull
            if ts(node["createdAt"]) >= before:
                return rows, True, total
            item = flatten_item(repo_id, repo["repo_full_name"], "issue", node)
            item["responders"] = None          # not fetched here
            rows.append(item)
        if data["rateLimit"]["remaining"] < LOW_POINTS:
            print(f"    rate budget low ({data['rateLimit']['remaining']}, "
                  f"resets {data['rateLimit']['resetAt']})")
            return rows, False, total
        if not conn["pageInfo"]["hasNextPage"]:
            return rows, True, total
        cursor = conn["pageInfo"]["endCursor"]


def save(stamp: str, repo_name: str, rows: list) -> None:
    df = pd.DataFrame(rows)
    for col in [c for c in df.columns if c.endswith("_at")]:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    out = RAW / "issues_prs" / f"dt={stamp}_open_{repo_name.replace('/', '_')}" / "part-0.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"    saved {len(df):>6} rows -> {out.relative_to(RAW.parent.parent)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="only this repo, e.g. pandas-dev/pandas")
    ap.add_argument("--before", default="2025-10-01",
                    help="only issues created before this date (the analysis start)")
    ap.add_argument("--max-minutes", type=int, default=55)
    args = ap.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set in .env")
    before = datetime.fromisoformat(args.before).replace(tzinfo=timezone.utc)

    repos = pd.read_csv(SEED).dropna(subset=["repo_id"])
    if args.repo:
        repos = repos[repos["repo_full_name"] == args.repo]
        if repos.empty:
            raise SystemExit(f"{args.repo} is not in seeds/repos.csv")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    deadline = time.time() + args.max_minutes * 60
    ok = bad = 0
    for _, repo in repos.iterrows():
        name = repo["repo_full_name"]
        print(f"{name:<45}")
        try:
            rows, complete, total = pull_repo(repo, token, before, deadline)
        except Exception as exc:                          # noqa: BLE001
            bad += 1
            print(f"    FAILED: {exc!r} - continuing")
            continue
        print(f"    {len(rows):>6} old open issues  (GitHub reports {total} open in total)")
        if rows:
            save(stamp, name, rows)
        if complete:
            ok += 1
        else:
            bad += 1
            print("    incomplete - re-run this repo later with --repo")
        if time.time() > deadline:
            break
    print(f"\nrepos complete {ok} | incomplete or failed {bad}")


if __name__ == "__main__":
    main()
