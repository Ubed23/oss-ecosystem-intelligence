"""Report which tracked repositories are archived on GitHub, and when each was
last pushed to.

    python scripts/check_archived.py

Why this exists: the health score is built from activity patterns and never
reads GitHub's `archived` flag. An archived repository has no new activity, and
depending on how nulls are ranked it can look healthy rather than dead.
python-bigquery is the case that exposed this.

Lookups use the numeric repo_id, not the name, so renamed repositories still
resolve (three of the thirty were renamed during the window).
"""
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seeds" / "repos.csv"


def main() -> None:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set in .env")
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}

    seed = pd.read_csv(SEED).dropna(subset=["repo_id"])
    rows = []
    for _, r in seed.iterrows():
        resp = requests.get(f"https://api.github.com/repositories/{int(r.repo_id)}",
                            headers=headers, timeout=30)
        if resp.status_code != 200:
            rows.append({"repo": r.repo_full_name, "archived": None,
                         "last_push": None, "months_idle": None,
                         "note": f"HTTP {resp.status_code}"})
            continue
        b = resp.json()
        pushed = pd.Timestamp(b["pushed_at"]).date()
        rows.append({"repo": b["full_name"], "archived": b["archived"],
                     "last_push": pushed.isoformat(),
                     "months_idle": round((date.today() - pushed).days / 30.4, 1),
                     "note": ""})
        time.sleep(0.2)

    df = pd.DataFrame(rows).sort_values(["archived", "months_idle"],
                                        ascending=[False, False], na_position="last")
    print(df.to_string(index=False))

    archived = df[df.archived == True]  # noqa: E712
    failed = df[df.note != ""]
    print(f"\narchived ({len(archived)}):", archived.repo.tolist())
    print(f"idle 6+ months, not archived: "
          f"{df[(df.archived == False) & (df.months_idle >= 6)].repo.tolist()}")
    if len(failed):
        print(f"lookups that failed ({len(failed)}):", failed.repo.tolist())


if __name__ == "__main__":
    main()