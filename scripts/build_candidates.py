"""Section 5.3 - build a defensible candidate list instead of picking from memory.

    python scripts/build_candidates.py --top 300

What it does:
  1. Downloads the public top-PyPI-packages list (hugovk, updated monthly).
  2. Takes the top N by download count.
  3. Asks the PyPI JSON API for each package's metadata.
  4. Extracts the GitHub repo from project_urls / home_page.
  5. Writes seeds/candidates.csv for you to filter BY HAND.

The hand-filtering step is deliberate. The output is a candidate pool, not the
final seed file - you still choose the ecosystem and assign criticality_tier
yourself, and you should be able to state the rule you used.
"""
import argparse
import csv
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "seeds" / "candidates.csv"
TOP_LIST = ("https://raw.githubusercontent.com/hugovk/top-pypi-packages/"
            "main/top-pypi-packages.json")
PYPI = "https://pypi.org/pypi/{pkg}/json"
GH = re.compile(r"github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)", re.I)


def github_repo(info: dict) -> str | None:
    """Find the GitHub repo in a PyPI metadata blob, preferring explicit links."""
    urls = dict(info.get("project_urls") or {})
    ordered = [v for k, v in urls.items()
               if any(w in k.lower() for w in ("source", "repo", "code", "github"))]
    ordered += list(urls.values()) + [info.get("home_page") or ""]
    for url in ordered:
        m = GH.search(url or "")
        if m:
            return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=300, help="how many packages to inspect")
    args = ap.parse_args()

    print(f"downloading the top-PyPI-packages list ...")
    rows = requests.get(TOP_LIST, timeout=60).json()["rows"][: args.top]

    out = []
    for i, row in enumerate(rows, 1):
        pkg = row["project"]
        try:
            info = requests.get(PYPI.format(pkg=pkg), timeout=30).json()["info"]
        except Exception as exc:
            print(f"  {pkg}: {exc}")
            continue
        repo = github_repo(info)
        out.append({
            "repo_full_name": repo or "",
            "repo_id": "",
            "package_name": pkg,
            "ecosystem": "",
            "category": "",
            "criticality_tier": "",
            "downloads_rank": i,
            "summary": (info.get("summary") or "")[:90],
        })
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}")
        time.sleep(0.15)

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    found = sum(1 for r in out if r["repo_full_name"])
    print(f"\nwrote {OUT} - {len(out)} packages, {found} with a GitHub repo")
    print("Next: open it, keep 20-40 rows in ONE ecosystem, fill in the blank")
    print("columns, and save the result as seeds/repos.csv")


if __name__ == "__main__":
    main()
