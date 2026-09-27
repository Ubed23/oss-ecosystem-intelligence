"""GitHub GraphQL -> issues, pull requests, and contribution records.

This is the PRIMARY source for the project. Two source problems forced that:

  1. 2025-10-07: GitHub stripped event payloads (no commits array, no
     author_association, PR payloads cut to id/url/number/head/base, merged
     PRs no longer reliably emitting events). GH Archive mirrors the Events
     API, so it inherited every gap.
  2. Early 2026 onwards: GH Archive event fidelity degraded badly - see
     docs/decisions/0002-gharchive-fidelity.md. Recent months are missing a
     large share of events.

So everything metric-bearing comes from here, and GH Archive is kept only for
pre-2026 history in the backtest.

Two outputs per run:
  data/raw/issues_prs/dt=<date>/part-0.parquet     one row per issue or PR
  data/raw/contributions/dt=<date>/part-0.parquet  one row per person-action

The second table replaces GH Archive as the input to contributor cohorts.
A contribution is work: opening an issue or PR, commenting, or reviewing.
Stars and forks are interest, not work, and are deliberately absent.

Usage
    python scripts/pull_github_graphql.py --since 2025-10-01      # backfill
    python scripts/pull_github_graphql.py                          # daily
    python scripts/pull_github_graphql.py --repo pandas-dev/pandas # one repo
    python scripts/pull_github_graphql.py --since 2025-10-01 --max-minutes 50

The backfill WILL hit the 5,000-point hourly limit. That is expected: the
script stops cleanly, saves what it has, and records per-repo watermarks, so
re-running an hour later resumes instead of restarting.
"""
import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seeds" / "repos.csv"
RAW = ROOT / "data" / "raw"
STATE = ROOT / "state" / "graphql_watermarks.json"

ENDPOINT = "https://api.github.com/graphql"
MAINTAINER = {"OWNER", "MEMBER", "COLLABORATOR"}
PAGE = 50            # items per request
COMMENTS = 10        # enough to find the first maintainer reply past bot noise
REVIEWS = 5
LOW_POINTS = 300     # stop a repo when the budget gets this thin

FIELDS = """
      number createdAt updatedAt closedAt state
      author { login }
      authorAssociation
      labels(first: 20) { nodes { name } }
      comments(first: %d) { nodes { createdAt authorAssociation author { login } } }
""" % COMMENTS

PR_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  rateLimit { remaining resetAt cost }
  repository(owner:$owner, name:$name) {
    pullRequests(first:%d, after:$cursor, orderBy:{field:UPDATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        %s
        mergedAt
        reviews(first:%d) { nodes { createdAt authorAssociation author { login } } }
      }
    }
  }
}
""" % (PAGE, FIELDS, REVIEWS)

ISSUE_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  rateLimit { remaining resetAt cost }
  repository(owner:$owner, name:$name) {
    issues(first:%d, after:$cursor, orderBy:{field:UPDATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}
""" % (PAGE, FIELDS)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def is_bot(login: str | None) -> bool:
    if not login:
        return True
    low = login.lower()
    return low.endswith("[bot]") or low in {
        "dependabot", "codecov-commenter", "pyup-bot", "web-flow", "stale",
        "github-actions", "renovate", "mergify", "sonarcloud",
    }


def read_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def write_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True))


def gql(query: str, variables: dict, token: str, attempt: int = 0) -> dict:
    """POST with exponential backoff on the statuses GitHub actually returns."""
    resp = requests.post(ENDPOINT, json={"query": query, "variables": variables},
                         headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code in (403, 429, 502, 503) and attempt < 5:
        wait = 2 ** (attempt + 1)
        print(f"    HTTP {resp.status_code}, retrying in {wait}s")
        time.sleep(wait)
        return gql(query, variables, token, attempt + 1)
    resp.raise_for_status()
    body = resp.json()
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def first_maintainer_response(node: dict) -> str | None:
    """Earliest comment or review by a maintainer who is not the author.

    Excluding the author matters: a maintainer opening their own issue and
    commenting on it would otherwise show a response time of zero and drag
    the whole project's median down.
    """
    author = (node.get("author") or {}).get("login")
    stamps = []
    for key in ("comments", "reviews"):
        for c in (node.get(key) or {}).get("nodes") or []:
            login = (c.get("author") or {}).get("login")
            if c.get("authorAssociation") in MAINTAINER and login != author and not is_bot(login):
                stamps.append(c["createdAt"])
    return min(stamps) if stamps else None


def flatten_item(repo_id: int, full_name: str, kind: str, node: dict) -> dict:
    return {
        "repo_id": repo_id,
        "repo_full_name": full_name,
        "kind": kind,
        "number": node["number"],
        "created_at": node["createdAt"],
        "updated_at": node["updatedAt"],
        "closed_at": node.get("closedAt"),
        "merged_at": node.get("mergedAt"),
        "state": node.get("state"),
        "author": (node.get("author") or {}).get("login"),
        "author_association": node.get("authorAssociation"),
        "labels": "|".join(n["name"].lower() for n in (node["labels"]["nodes"] or [])),
        "first_response_at": first_maintainer_response(node),
    }


def extract_contributions(repo_id: int, kind: str, node: dict) -> list[dict]:
    """Person-actions derived from one issue or PR.

    This is what replaces GH Archive for cohort retention. Opening, commenting
    and reviewing all count as work; bots are dropped at source.
    """
    rows = []
    author = (node.get("author") or {}).get("login")
    if not is_bot(author):
        rows.append({"repo_id": repo_id, "actor": author,
                     "contributed_at": node["createdAt"],
                     "contribution_type": f"open_{kind}"})
    for key, label in (("comments", "comment"), ("reviews", "review")):
        for c in (node.get(key) or {}).get("nodes") or []:
            login = (c.get("author") or {}).get("login")
            if not is_bot(login):
                rows.append({"repo_id": repo_id, "actor": login,
                             "contributed_at": c["createdAt"],
                             "contribution_type": label})
    return rows


# --------------------------------------------------------------------------
# per-repo pull
# --------------------------------------------------------------------------

def pull_connection(kind: str, query: str, field: str, repo, token: str,
                    since: datetime, deadline: float) -> tuple[list, list, bool]:
    """Page newest-first, stop at the watermark. Returns (items, contributions, complete)."""
    owner, name = repo["repo_full_name"].split("/")
    repo_id = int(repo["repo_id"])
    cursor, items, contribs = None, [], []

    while True:
        if time.time() > deadline:
            print(f"    time budget reached during {kind}s")
            return items, contribs, False

        data = gql(query, {"owner": owner, "name": name, "cursor": cursor}, token)
        conn = data["repository"][field]

        for node in conn["nodes"]:
            if ts(node["updatedAt"]) < since:
                return items, contribs, True          # caught up
            items.append(flatten_item(repo_id, repo["repo_full_name"], kind, node))
            contribs += extract_contributions(repo_id, kind, node)

        rl = data["rateLimit"]
        if rl["remaining"] < LOW_POINTS:
            print(f"    rate budget low ({rl['remaining']}, resets {rl['resetAt']})")
            return items, contribs, False

        if not conn["pageInfo"]["hasNextPage"]:
            return items, contribs, True
        cursor = conn["pageInfo"]["endCursor"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO date for a backfill; otherwise the watermark is used")
    ap.add_argument("--repo", help="only this repo, e.g. pandas-dev/pandas")
    ap.add_argument("--lookback-days", type=int, default=3,
                    help="default window when a repo has no watermark yet")
    ap.add_argument("--max-minutes", type=int, default=55,
                    help="stop cleanly before this, so a CI job never hangs")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch repos that already completed")
    args = ap.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set in .env")

    repos = pd.read_csv(SEED).dropna(subset=["repo_id"])
    if args.repo:
        repos = repos[repos["repo_full_name"] == args.repo]
        if repos.empty:
            raise SystemExit(f"{args.repo} is not in seeds/repos.csv")

    state = read_state()
    deadline = time.time() + args.max_minutes * 60
    all_items: list[dict] = []
    all_contribs: list[dict] = []
    done = incomplete = 0


    for _, repo in repos.iterrows():
        key = repo["repo_full_name"]
        if args.since and key in state and not args.force:
            print(f"{key:<45} already complete, skipping")
            continue
        if args.since:
            since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        elif key in state:
            since = ts(state[key])
        else:
            since = datetime.now(timezone.utc) - timedelta(days=args.lookback_days)

        started = datetime.now(timezone.utc)
        print(f"{key:<45} since {since:%Y-%m-%d}")

        pr_i, pr_c, pr_ok = pull_connection("pr", PR_QUERY, "pullRequests",
                                            repo, token, since, deadline)
        is_i, is_c, is_ok = pull_connection("issue", ISSUE_QUERY, "issues",
                                            repo, token, since, deadline)

        all_items += pr_i + is_i
        all_contribs += pr_c + is_c
        print(f"    {len(pr_i):>5} PRs  {len(is_i):>5} issues  "
              f"{len(pr_c) + len(is_c):>6} contributions")

        # Only advance the watermark when BOTH connections finished. Advancing
        # on partial success would permanently skip whatever was not fetched.
        if pr_ok and is_ok:
            state[key] = started.isoformat()
            done += 1
        else:
            incomplete += 1
            print("    incomplete - watermark left unchanged, re-run to finish")
            if time.time() > deadline:
                break

    partition = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    for name, rows in (("issues_prs", all_items), ("contributions", all_contribs)):
        if not rows:
            continue
        df = pd.DataFrame(rows)
        for col in [c for c in df.columns if c.endswith("_at")]:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
        if name == "issues_prs":
            df = df.sort_values("updated_at").drop_duplicates(
                subset=["repo_id", "kind", "number"], keep="last")
        else:
            df = df.drop_duplicates()
        out = RAW / name / f"dt={partition}" / "part-0.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
        print(f"saved {len(df):>7} rows -> {out.relative_to(ROOT)}")

    write_state(state)
    print(f"\nrepos complete {done} | incomplete {incomplete}")
    if incomplete:
        print("Re-run the same command in an hour; watermarks resume where this stopped.")


if __name__ == "__main__":
    main()