"""Fill the repo_id column in seeds/repos.csv from the GitHub REST API.

Run once, from the project root:

    python scripts/resolve_repo_ids.py

Why repo_id and not the name: repositories get renamed, transferred between
organisations, or moved to a foundation. Keyed on the name, a renamed project
silently splits into two entities - one that looks dead, one that looks newborn.
The numeric ID never changes. The API also follows renames, so this script
writes back the canonical full_name it was redirected to.

Safe to re-run: rows that already have an id are skipped.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
import os  # noqa: E402  - after load_dotenv so .env is populated

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seeds" / "repos.csv"
API = "https://api.github.com/repos/{full_name}"


def main() -> None:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("WARNING: no GITHUB_TOKEN found - limited to 60 requests/hour.\n")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if not SEED.exists():
        sys.exit(f"Seed file not found: {SEED}")

    df = pd.read_csv(SEED)
    if "repo_id" not in df.columns:
        sys.exit("seeds/repos.csv has no repo_id column.")

    resolved = skipped = failed = 0

    for idx, row in df.iterrows():
        if pd.notna(row["repo_id"]):
            skipped += 1
            continue

        name = str(row["repo_full_name"]).strip()
        resp = requests.get(API.format(full_name=name), headers=headers, timeout=30)

        if resp.status_code == 404:
            print(f"  NOT FOUND   {name}  (typo, or the repo was deleted)")
            failed += 1
            continue
        if resp.status_code == 403:
            print("\nRate limited. Wait an hour, or add GITHUB_TOKEN to .env, then re-run.")
            break
        resp.raise_for_status()

        body = resp.json()
        df.at[idx, "repo_id"] = body["id"]

        if body["full_name"] != name:
            print(f"  RENAMED     {name} -> {body['full_name']}")
            df.at[idx, "repo_full_name"] = body["full_name"]

        print(f"  {body['full_name']:<45} {body['id']}")
        resolved += 1
        time.sleep(0.3)

    df["repo_id"] = df["repo_id"].astype("Int64")  # nullable int, no .0 suffix
    df.to_csv(SEED, index=False)

    print(f"\nresolved {resolved} | already had an id {skipped} | failed {failed}")
    missing = int(df["repo_id"].isna().sum())
    print("All rows have an id." if missing == 0 else f"{missing} row(s) still missing an id.")


if __name__ == "__main__":
    main()
