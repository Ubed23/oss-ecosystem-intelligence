"""Publish the DuckDB marts to Google Sheets - the serving layer for Tableau.

    python scripts/to_sheets.py --dry-run     # show what would be written
    python scripts/to_sheets.py

Why a spreadsheet sits in the middle of a data pipeline: Tableau Public cannot
hold a live connection to a database, and the only source it auto-refreshes is
Google Sheets, once every 24 hours. So the Sheet is not a workaround, it is the
one automatic refresh path the free tier offers.

Three things this has to get right, each of which otherwise breaks silently:

  * gspread cannot serialise pandas NaN or datetime objects. Everything is
    converted to strings or blanks before upload.
  * Tabs are CLEARED before writing. Appending makes row counts grow every day
    and Tableau starts double-counting.
  * Marts stay small. Sheets caps at 10 million cells and Tableau refreshes far
    more reliably against small tabs, so only aggregates go up - never raw
    events.

Requires: the Sheet shared with the service account's client_email as Editor.
That step is easy to skip and produces an authentication-looking error that is
really a permissions error.
"""
import argparse
import os
from pathlib import Path

import duckdb
import gspread
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "warehouse" / "oss.duckdb"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

# One tab per mart. Keep every query aggregated - if a tab exceeds a few
# thousand rows, aggregate it further rather than raising the limit.
TABS = {
    "health_current": """
        select repo_id, repo_full_name, ecosystem, criticality_tier,
               health_score, health_tier,
               bus_factor_50, top_author_share,
               round(ttfr_p50_hours, 1) as ttfr_p50_hours,
               round(ttfr_p90_hours, 1) as ttfr_p90_hours,
               round(unresponded_rate, 3) as unresponded_rate,
               items_opened_90d, prs_merged_90d, distinct_pr_authors_90d,
               bugs_open_at_month_end, active_contributors,
               round(retention_m3, 3) as retention_m3,
               median_release_gap_days, days_since_release,
               scorecard_overall, check_maintained, has_scorecard,
               -- component ranks drive the adjustable-weight parameters in Tableau
               round(bus_factor_score, 4)            as bus_factor_score,
               round(maintainer_activity_score, 4)   as maintainer_activity_score,
               round(response_time_score, 4)         as response_time_score,
               round(unresponded_score, 4)           as unresponded_score,
               round(bug_backlog_score, 4)           as bug_backlog_score,
               round(contributor_retention_score, 4) as contributor_retention_score
        from fct_repo_health_current
    """,
    "health_monthly": """
        select repo_id, cast(month_start as date) as month_start,
               round(ttfr_p50_hours, 1) as ttfr_p50_hours,
               round(ttfr_p90_hours, 1) as ttfr_p90_hours,
               items_opened, round(unresponded_rate, 3) as unresponded_rate,
               prs_merged, distinct_pr_authors,
               round(median_merge_hours, 1) as median_merge_hours,
               bugs_opened, bugs_open_at_month_end, active_contributors,
               bus_factor_50
        from fct_repo_health_monthly
        order by repo_id, month_start
    """,
    "health_score_monthly": """
        select repo_id,
               cast(month_start as date) as month_start,
               health_score,
               score_change_6m,
               round(bus_factor_score, 4)           as bus_factor_score,
               round(maintainer_activity_score, 4)  as maintainer_activity_score,
               round(response_time_score, 4)        as response_time_score,
               round(unresponded_score, 4)          as unresponded_score,
               round(bug_backlog_score, 4)          as bug_backlog_score,
               round(community_activity_score, 4)   as community_activity_score
        from fct_health_score_monthly
        order by repo_id, month_start
    """,

    "cohorts": """
        select repo_id, cast(cohort_month as date) as cohort_month,
               months_since, cohort_contributors, retained_contributors,
               round(retention_rate, 4) as retention_rate
        from fct_contributor_cohorts
        where months_since <= 6
        order by repo_id, cohort_month, months_since
    """,
    "releases": """
        select repo_id, tag_name, cast(published_at as date) as published_at,
               bugs_after, bugs_baseline, round(expected_bugs, 2) as expected_bugs,
               round(regression_ratio, 3) as regression_ratio
        from fct_release_reliability
        order by published_at desc
    """,
    "repos": """
        select repo_id, repo_full_name, package_name, ecosystem, category,
               criticality_tier, scorecard_overall, check_maintained,
               check_code_review, has_scorecard
        from dim_repo
    """,
    "source_fidelity": """
        select cast(month_start as date) as month_start,
               archive_events, api_items_created,
               round(archive_to_api_ratio, 3) as archive_to_api_ratio
        from fct_source_fidelity
        order by month_start
    """,
}


def clean(df: pd.DataFrame) -> list[list]:
    """Make a DataFrame safe for the Sheets API.

    gspread serialises to JSON, which has no NaN and no datetime. Both raise
    an opaque error if they reach the API, so they are converted here.
    """
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        elif df[col].dtype == "object":
            df[col] = df[col].astype(str).replace({"NaT": "", "None": "", "nan": ""})
        elif pd.api.types.is_bool_dtype(df[col]):
            df[col] = df[col].astype(str)
    df = df.astype(object).where(pd.notna(df), "")
    return [df.columns.tolist()] + df.values.tolist()


def write_tab(sheet, name: str, df: pd.DataFrame) -> None:
    values = clean(df)
    rows, cols = len(values), len(values[0])
    try:
        ws = sheet.worksheet(name)
        ws.clear()                      # never append: Tableau would double-count
        if ws.row_count < rows or ws.col_count < cols:
            ws.resize(rows=max(rows + 50, 100), cols=max(cols + 5, 10))
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=name, rows=max(rows + 50, 100), cols=max(cols + 5, 10))
    ws.update(values, value_input_option="RAW")
    print(f"  {name:<18} {rows - 1:>6} rows x {cols:>2} cols")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print shapes without touching the Sheet")
    ap.add_argument("--only", help="publish a single tab by name")
    args = ap.parse_args()

    if not DB.exists():
        raise SystemExit("warehouse/oss.duckdb not found. Run dbt build first.")
    con = duckdb.connect(str(DB), read_only=True)

    tabs = {args.only: TABS[args.only]} if args.only else TABS
    frames = {}
    total_cells = 0
    for name, sql in tabs.items():
        df = con.execute(sql).df()
        frames[name] = df
        total_cells += df.size
        if args.dry_run:
            print(f"  {name:<18} {len(df):>6} rows x {len(df.columns):>2} cols")

    meta = pd.DataFrame([
        {"key": "last_refreshed_utc", "value": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M")},
        {"key": "repositories", "value": str(len(frames.get("repos", frames[list(frames)[0]])))},
        {"key": "note", "value": "Rankings are robust to weighting; quartile tiers are not."},
    ])
    total_cells += meta.size

    print(f"\ntotal {total_cells:,} cells (Sheets limit is 10,000,000)")
    if total_cells > 2_000_000:
        print("WARNING: large for a Tableau refresh. Aggregate further before publishing.")
    if args.dry_run:
        print("\ndry run - nothing written")
        return

    gsheet_id = os.getenv("GSHEET_ID")
    if not gsheet_id:
        raise SystemExit("GSHEET_ID is not set in .env")
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json"), scopes=SCOPES)
    client = gspread.authorize(creds)

    try:
        sheet = client.open_by_key(gsheet_id)
    except gspread.exceptions.APIError as exc:
        print(f"\nCould not open the Sheet: {exc}")
        print("Most likely cause: the Sheet is not shared with the service account.")
        print("Share it as Editor with the address printed by:")
        print("  python -c \"import json; print(json.load(open('service_account.json'))['client_email'])\"")
        raise SystemExit(1)

    print(f"\npublishing to '{sheet.title}'")
    for name, df in frames.items():
        write_tab(sheet, name, df)
    write_tab(sheet, "meta", meta)

    print(f"\nhttps://docs.google.com/spreadsheets/d/{gsheet_id}")


if __name__ == "__main__":
    main()