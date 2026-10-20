"""Print every number quoted in the dashboard text boxes, from the warehouse.

    python scripts/dashboard_numbers.py

Run it after every refresh, then paste the values into the Key Insights text
boxes. Text written by hand goes stale (and did); numbers printed from the
same marts as the dashboard cannot disagree with it.
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "warehouse" / "oss.duckdb"), read_only=True)
con.execute("SET TimeZone='UTC'")
q = lambda sql: con.execute(sql).df()          # noqa: E731
pd.set_option("display.width", 200)


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


cur = q("select * from fct_repo_health_current order by health_score")
mon = q("""select cast(month_start as date) m, * exclude (month_start)
           from fct_repo_health_monthly
           where month_start < (select max(month_start) from fct_repo_health_monthly)
           order by m""")
n = len(cur)
avg = cur.health_score.mean()

print("=== EXECUTIVE OVERVIEW ===")
eco = q("""select ecosystem, count(*) n, round(avg(health_score),1) avg_score,
                  sum((health_tier='critical')::int) critical
           from fct_repo_health_current group by 1 order by 3""")
print(eco.to_string(index=False))
print(f"Average score {avg:.1f}. Lowest two: "
      + ", ".join(f"{r.repo_full_name.split('/')[1]} ({r.health_score})" for r in cur.head(2).itertuples()))
print("Tiers:", cur.health_tier.value_counts().to_dict())

print("\n=== MAINTAINER & RISK ===")
bf2 = cur[cur.bus_factor_50 <= 2]
bf3 = cur[cur.bus_factor_50 >= 3]
print(f"{len(bf2)} of {n} repos have bus factor <= 2; {int((bf2.health_score < avg).sum())} of them score below "
      f"the average ({avg:.1f}); {int((bf3.health_score < avg).sum())} of the {len(bf3)} with bus factor >= 3 do")
print("Bus factor 1:", ", ".join(r.split('/')[1] for r in cur[cur.bus_factor_50 == 1].repo_full_name))
mid = int(((cur.top_author_share >= .2) & (cur.top_author_share <= .5)).sum())
print(f"Top author share between 20% and 50%: {mid} of {n} ({pct(mid / n)})")
print(f"Bus factor 1 count (Contributor Sustainability tile): {int((cur.bus_factor_50 == 1).sum())}")

print("\n=== BUG BACKLOG ===")
b = mon.groupby("m").agg(open_bugs=("bugs_open_at_month_end", "sum"), opened=("bugs_opened", "sum")).reset_index()
first, last = b.iloc[0], b.iloc[-1]
print(f"Open bugs {first.open_bugs:,.0f} ({first.m:%b %Y}) -> {last.open_bugs:,.0f} ({last.m:%b %Y}), "
      f"change {pct(last.open_bugs / first.open_bugs - 1)}")
print(f"Bugs opened per month: {b.opened.min():,.0f} to {b.opened.max():,.0f}")
last_m = mon.m.max()
lm = mon[mon.m == last_m].merge(cur[["repo_id", "repo_full_name", "ecosystem", "health_tier"]], on="repo_id")
print("By ecosystem:", lm.groupby("ecosystem").bugs_open_at_month_end.sum().sort_values(ascending=False).head(4).astype(int).to_dict())
print("Top repos:", lm.sort_values("bugs_open_at_month_end", ascending=False).head(5)
      .apply(lambda r: f"{r.repo_full_name.split('/')[1]} ({int(r.bugs_open_at_month_end)}, {r.health_tier})", axis=1).tolist())

print("\n=== CONTRIBUTOR SUSTAINABILITY ===")
act = mon.groupby("m").active_contributors.sum()
print(f"Active contributor-repo pairs: {act.iloc[0]:,.0f} ({act.index[0]:%b %Y}) ... min {act.min():,.0f}, max {act.max():,.0f}; latest {act.iloc[-1]:,.0f}")
coh = q("""select months_since, sum(retained_contributors) r, sum(cohort_contributors) n
           from fct_contributor_cohorts where months_since <= 11 group by 1 order by 1""")
coh["rate"] = coh.r / coh.n
print("Retention by month:", {int(r.months_since): pct(r.rate, 1) for r in coh.itertuples() if r.months_since in (1, 3, 6)})
new = q("select cast(cohort_month as date) m, sum(cohort_contributors) n from fct_contributor_cohorts where months_since=0 group by 1 order by 1")
print(f"First-time contributors per month: {new.n.min():,.0f} to {new.n.max():,.0f}; peak {new.loc[new.n.idxmax(), 'm']:%b %Y}")

print("\n=== ENGINEERING OPERATIONS ===")
ops = mon.groupby("m").apply(lambda d: pd.Series({
    "items": d.items_opened.sum(), "prs": d.prs_merged.sum(),
    "unans": (d.unresponded_rate * d.items_opened).sum() / d.loc[d.unresponded_rate.notna(), "items_opened"].sum(),
    "med_ttfr": d.ttfr_p50_hours.median(), "p90": d.ttfr_p90_hours.median(),
    "merge_h": d.median_merge_hours.median()}), include_groups=False)
print(ops.round(2).to_string())
print(f"Items {ops["items"].iloc[0]:,.0f} -> {ops["items"].iloc[-1]:,.0f}; PRs merged {ops["prs"].iloc[0]:,.0f} -> {ops["prs"].iloc[-1]:,.0f} "
      f"({pct(ops["prs"].iloc[-1] / ops["prs"].iloc[0] - 1, 1)})")

print("\n=== RELEASES & QUALITY ===")
rel = q("""select r.*, d.repo_full_name from fct_release_reliability r join dim_repo d using (repo_id)
           where window_complete""")
j = rel[rel.regression_ratio.notna() & (rel.expected_bugs >= 2)]
print(f"{len(rel)} completed releases; {len(j)} judgeable; "
      f"{int(j.regression_ratio.between(.75, 1.5).sum())} within 0.75-1.5x ({pct(j.regression_ratio.between(.75, 1.5).mean())}); "
      f"{int((j.regression_ratio > 3).sum())} above 3x; median ratio {j.regression_ratio.median():.2f}")
print("Largest:", j.sort_values("regression_ratio", ascending=False).head(3)
      .apply(lambda r: f"{r.repo_full_name.split('/')[1]} {r.tag_name} ({r.regression_ratio:.1f}x)", axis=1).tolist())

print("\n=== SENSITIVITY (docs/sensitivity_summary.md) ===")
print((ROOT / "docs" / "sensitivity_summary.md").read_text(encoding="utf-8")[:900])
