"""Build the text for the dashboard's Key Insights cards from the marts.

    python scripts/insights.py            # print every insight
    (also imported by scripts/to_sheets.py, which publishes them as the
     `insights` tab of the Google Sheet)

Why this exists: text typed by hand goes stale (it did - the dashboard still
quoted an old open-bug count). Here every number is computed from the same
marts as the charts, so text and charts cannot disagree, and the text changes
by itself each time the pipeline is rebuilt and published.

Rules the wording follows:
  * Describe, do not interpret. "Open bugs fell 20%" is computed; "because the
    team improved" is not something the data can say.
  * Direction words (rose / fell / was broadly flat) are chosen by the numbers,
    never hard-coded.
  * The partial current month is dropped, exactly like dashboard_numbers.py.

Output: one row per card, four cards per dashboard page. Columns
    page      which dashboard page the text belongs to
    ord       1-4, the card's position (1 red, 2 blue, 3 purple, 4 amber)
    headline  short bold title
    text      the sentence(s) under it
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "warehouse" / "oss.duckdb"

FLAT = 0.05            # a change smaller than +/-5% is described as broadly flat


def pct(x: float, d: int = 0) -> str:
    return f"{x * 100:.{d}f}%"


def direction(change: float, up: str = "rose", down: str = "fell",
              flat: str = "was broadly flat") -> str:
    """Pick a verb from the size of the change."""
    if change > FLAT:
        return up
    if change < -FLAT:
        return down
    return flat


def moved(change: float, label: str, end: str) -> str:
    """'<label> rose to 19.5 hours' / '<label> was broadly flat at 19.5 hours'."""
    if abs(change) <= FLAT:
        return f"{label} was broadly flat at {end}"
    return f"{label} {'rose' if change > 0 else 'fell'} to {end}"


def short(repo_full_name: str) -> str:
    return repo_full_name.split("/")[-1]


def names(frame: pd.DataFrame, n: int = 3) -> str:
    return ", ".join(short(r) for r in frame.head(n).repo_full_name)


ECO_LABELS = {"pydata": "PyData", "ml": "ML", "mlops": "MLOps", "bi": "BI", "viz": "Viz"}


def eco_label(name: str) -> str:
    return ECO_LABELS.get(name, name.capitalize())


def month_label(ts) -> str:
    return pd.Timestamp(ts).strftime("%b %Y")


def build_insights(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    q = lambda sql: con.execute(sql).df()          # noqa: E731

    cur = q("select * from fct_repo_health_current order by health_score")
    # complete months only: the newest month in the mart is partial
    mon = q("""select cast(month_start as date) as m, * exclude (month_start)
               from fct_repo_health_monthly
               where month_start < (select max(month_start) from fct_repo_health_monthly)
               order by m""")
    n = len(cur)
    avg = cur.health_score.mean()
    rows: list[dict] = []

    def add(page, headline, text):
        rows.append({"page": page, "ord": sum(r["page"] == page for r in rows) + 1,
                     "headline": headline, "text": text})

    # ================================================================ executive
    # 1. how many repositories are at risk
    risky = int(cur.health_tier.isin(["critical", "at_risk"]).sum())
    low2 = ", ".join(f"{short(r.repo_full_name)} ({r.health_score:.1f})"
                     for r in cur.head(2).itertuples())
    tiers = cur.health_tier.value_counts()
    add("executive", f"{risky} of {n} repositories are at risk or critical",
        f"That is {pct(risky / n)} of the tracked set. Tiers: "
        f"{int(tiers.get('critical', 0))} critical, {int(tiers.get('at_risk', 0))} at risk, "
        f"{int(tiers.get('stable', 0))} stable, {int(tiers.get('healthy', 0))} healthy. "
        f"Average health score is {avg:.1f}; lowest two are {low2}.")

    # 2. weakest ecosystem
    eco = (cur.groupby("ecosystem")
              .agg(n=("repo_id", "count"), avg=("health_score", "mean"),
                   critical=("health_tier", lambda s: int((s == "critical").sum())))
              .reset_index())
    eco2 = eco[eco.n >= 2].sort_values("avg")          # one-repo ecosystems are noise
    if len(eco2):
        e = eco2.iloc[0]
        who = ("all of them are classified as critical" if e.critical == e.n
               else f"{int(e.critical)} of {int(e.n)} are classified as critical")
        add("executive", f"{eco_label(e.ecosystem)} has the lowest average score",
            f"Among ecosystems with two or more repositories, {e.ecosystem} averages "
            f"{e.avg:.1f} across {int(e.n)} repositories; {who}.")

    # 3. slowest to respond
    resp = cur[cur.unresponded_rate.notna()].sort_values("unresponded_rate", ascending=False)
    if len(resp):
        top = ", ".join(f"{short(r.repo_full_name)} ({pct(r.unresponded_rate)})"
                        for r in resp.head(3).itertuples())
        add("executive", f"Unanswered share is highest in {short(resp.iloc[0].repo_full_name)}",
            f"Share of items with no maintainer reply within 7 days, last 90 days: {top}. "
            f"The median repository is at {pct(resp.unresponded_rate.median())}.")

    # 4. closest to moving up a tier
    crit = cur[cur.health_tier == "critical"]
    atrisk = cur[cur.health_tier == "at_risk"]
    if len(crit) and len(atrisk):
        cutoff = atrisk.health_score.min()
        near = crit[crit.health_score >= cutoff - 5].sort_values("health_score", ascending=False)
        close = ", ".join(f"{short(r.repo_full_name)} ({r.health_score:.1f})"
                          for r in crit.sort_values("health_score", ascending=False).head(3).itertuples())
        head = (f"{len(near)} critical repositories are within 5 points of at risk" if len(near)
                else "No critical repository is within 5 points of at risk")
        add("executive", head,
            f"The at-risk tier starts at {cutoff:.1f}. Highest-scoring critical repositories: "
            f"{close}. Scores are percentile ranks within these {n} repositories, so they are relative.")

    # ============================================================ maintainer_risk
    bf2 = cur[cur.bus_factor_50 <= 2]
    bf3 = cur[cur.bus_factor_50 >= 3]
    bf1 = ", ".join(short(r) for r in cur[cur.bus_factor_50 == 1].repo_full_name) or "none"
    add("maintainer_risk",
        f"{len(bf2)} of {n} repositories have a bus factor of 2 or less",
        f"{int((bf2.health_score < avg).sum())} of them score below the portfolio "
        f"average ({avg:.1f}), against {int((bf3.health_score < avg).sum())} of the "
        f"{len(bf3)} with a bus factor of 3 or more.")
    mid = int(((cur.top_author_share >= .2) & (cur.top_author_share <= .5)).sum())
    add("maintainer_risk", f"Bus factor 1: {int((cur.bus_factor_50 == 1).sum())} repositories",
        f"Bus factor 1 means one author accounts for at least half of merged PRs: {bf1}. "
        f"The top author's share is between 20% and 50% in {mid} of {n} repositories.")

    t1 = cur[cur.criticality_tier == "tier_1"]
    t1_risk = t1[t1.health_tier.isin(["critical", "at_risk"])].sort_values("health_score")
    add("maintainer_risk",
        f"{len(t1_risk)} of {len(t1)} tier-1 repositories are at risk or critical",
        (f"Tier 1 is the foundational set in the seed list. At risk or critical: {names(t1_risk, 6)}"
         + (f" and {len(t1_risk) - 6} more." if len(t1_risk) > 6 else ".")
         if len(t1_risk) else "Tier 1 is the foundational set in the seed list; none of it is at risk or critical."))

    auth = cur.distinct_pr_authors_90d
    few = cur[auth <= 5]
    add("maintainer_risk", "Few people merge work in many repositories",
        f"In the last 90 days the median repository had {auth.median():.0f} distinct PR authors; "
        f"{len(few)} of {n} had 5 or fewer. The median top-author share of merged PRs is "
        f"{pct(cur.top_author_share.median())}.")

    # ================================================================ bug_backlog
    b = (mon.groupby("m")
            .agg(open_bugs=("bugs_open_at_month_end", "sum"), opened=("bugs_opened", "sum"))
            .reset_index())
    if len(b) >= 2:
        f, l = b.iloc[0], b.iloc[-1]
        chg = l.open_bugs / f.open_bugs - 1
        add("bug_backlog", f"Open bugs {direction(chg)} {pct(abs(chg))}"
            if abs(chg) > FLAT else "Open bugs were broadly flat",
            f"Open bugs went from {f.open_bugs:,.0f} (end of {month_label(f.m)}) to "
            f"{l.open_bugs:,.0f} (end of {month_label(l.m)}), a change of {chg * 100:+.0f}%. "
            f"The count includes older issues that are still open.")
        k = min(3, len(b) // 2)
        first3, last3 = b.opened.head(k).mean(), b.opened.tail(k).mean()
        add("bug_backlog", "Bugs opened per month",
            f"Between {b.opened.min():,.0f} and {b.opened.max():,.0f} a month. The first "
            f"{k} months averaged {first3:,.0f}; the latest {k} averaged {last3:,.0f}.")

    last_m = mon.m.max()
    lm = (mon[mon.m == last_m]
          .merge(cur[["repo_id", "repo_full_name", "ecosystem", "health_tier"]], on="repo_id"))
    eco_b = lm.groupby("ecosystem").bugs_open_at_month_end.sum().sort_values(ascending=False)
    if len(eco_b):
        top3 = ", ".join(f"{eco_label(e)} ({int(v):,})" for e, v in eco_b.head(3).items())
        add("bug_backlog", f"{eco_label(eco_b.index[0])} holds the most open bugs",
            f"Open bugs at the end of {month_label(last_m)} by ecosystem: {top3}. "
            f"That is {pct(eco_b.iloc[0] / eco_b.sum())} of the {int(eco_b.sum()):,} open across the 30 repositories.")
    top_r = lm.sort_values("bugs_open_at_month_end", ascending=False).head(4)
    if len(top_r):
        listing = ", ".join(f"{short(r.repo_full_name)} ({int(r.bugs_open_at_month_end):,}, "
                            f"{r.health_tier.replace('_', ' ')})" for r in top_r.itertuples())
        add("bug_backlog", f"Largest backlogs: {names(top_r, 4)}",
            f"Open bugs at the end of {month_label(last_m)}, with each repository's health tier: {listing}.")

    # ================================================================ contributors
    act = mon.groupby("m").active_contributors.sum()
    if len(act) >= 2:
        chg = act.iloc[-1] / act.iloc[0] - 1
        add("contributors", f"Active contributors {direction(chg, flat='were broadly flat')}",
            f"Active contributor-repo pairs went from {act.iloc[0]:,.0f} ({month_label(act.index[0])}) "
            f"to {act.iloc[-1]:,.0f} ({month_label(act.index[-1])}); the range over the period "
            f"was {act.min():,.0f} to {act.max():,.0f}. A person active in two repositories counts twice.")
    new = q("""select cast(cohort_month as date) as m, sum(cohort_contributors) as n
               from fct_contributor_cohorts where months_since = 0 group by 1 order by 1""")
    coh = q("""select months_since, sum(retained_contributors) as r, sum(cohort_contributors) as n
               from fct_contributor_cohorts where months_since <= 11 group by 1 order by 1""")
    coh["rate"] = coh.r / coh.n
    ret = {int(r.months_since): r.rate for r in coh.itertuples()}
    if len(new):
        peak = new.loc[new.n.idxmax(), "m"]
        add("contributors", "First-time contributors per month",
            f"Between {new.n.min():,.0f} and {new.n.max():,.0f} a month, peaking in {month_label(peak)}. "
            f"Months are counted from each person's first contribution to a repository, from "
            f"{month_label(new.m.min())}.")
    if 1 in ret and 6 in ret:
        later = max(k for k in ret if k <= 10)
        add("contributors",
            f"Retention is {pct(ret[1], 1)} after one month and {pct(ret[6], 1)} after six",
            f"Share of new contributors still active: {pct(ret[1], 1)} at month 1, "
            f"{pct(ret.get(3, float('nan')), 1)} at month 3, {pct(ret[6], 1)} at month 6 and "
            f"{pct(ret[later], 1)} at month {later}. These are pooled across all repositories.")
    over50 = int((cur.bus_factor_50 == 1).sum())
    add("contributors", f"{over50} repositories depend on a single main author",
        f"The median top-author share of merged PRs is {pct(cur.top_author_share.median())}; "
        f"{over50} repositories have a bus factor of 1 ({bf1}).")

    # ============================================================ engineering_ops
    def month_stats(d: pd.DataFrame) -> pd.Series:
        ok = d.unresponded_rate.notna()
        denom = d.loc[ok, "items_opened"].sum()
        return pd.Series({
            "items": d.items_opened.sum(), "prs": d.prs_merged.sum(),
            "unans": (d.unresponded_rate * d.items_opened).sum() / denom if denom else float("nan"),
            "ttfr": d.ttfr_p50_hours.median(), "p90": d.ttfr_p90_hours.median(),
            "merge_h": d.median_merge_hours.median()})

    ops = mon.groupby("m").apply(month_stats, include_groups=False)
    if len(ops) >= 2:
        a, z = ops.iloc[0], ops.iloc[-1]
        fm, lmn = month_label(ops.index[0]), month_label(ops.index[-1])
        ic, pc = z["items"] / a["items"] - 1, z["prs"] / a["prs"] - 1
        add("engineering_ops", f"Items opened {direction(ic, flat='were broadly flat')}",
            f"Items opened went from {a['items']:,.0f} ({fm}) to {z['items']:,.0f} ({lmn}); "
            f"PRs merged went from {a['prs']:,.0f} to {z['prs']:,.0f} ({pc * 100:+.1f}%).")
        tc = z["ttfr"] / a["ttfr"] - 1
        add("engineering_ops", moved(tc, "Median first response", f"{z['ttfr']:.1f} hours"),
            f"It was {a['ttfr']:.1f} hours in {fm} and {z['ttfr']:.1f} hours in {lmn}; across months "
            f"it ranged from {ops.ttfr.min():.1f} to {ops.ttfr.max():.1f} hours (median of the "
            f"repositories' monthly medians). The typical repository's 90th-percentile response "
            f"was {z['p90']:.0f} hours in {lmn}.")
        add("engineering_ops", f"Unanswered share went from {pct(a['unans'])} to {pct(z['unans'])}",
            f"Share of items with no maintainer reply within 7 days, {fm} to {lmn}; across months "
            f"it ranged from {pct(ops.unans.min())} to {pct(ops.unans.max())}. Items younger than "
            f"7 days and items opened by a maintainer are left out.")
        mc = z["merge_h"] / a["merge_h"] - 1
        add("engineering_ops", moved(mc, "Median time to merge", f"{z['merge_h']:.1f} hours"),
            f"It was {a['merge_h']:.1f} hours in {fm} and {z['merge_h']:.1f} hours in {lmn}; across "
            f"months it ranged from {ops.merge_h.min():.1f} to {ops.merge_h.max():.1f} hours "
            f"(median of the repositories' monthly medians).")

    # ================================================== releases and quality
    rel = q("""select r.*, d.repo_full_name from fct_release_reliability r
               join dim_repo d using (repo_id) where window_complete""")
    j = rel[rel.regression_ratio.notna() & (rel.expected_bugs >= 2)]
    if len(j):
        within = j.regression_ratio.between(.75, 1.5)
        add("releases", "Most releases land near the expected bug count"
            if within.mean() >= .5 else "Fewer than half of releases land near the expected bug count",
            f"{len(rel)} releases have a complete 14-day follow-up; {len(j)} had a baseline "
            f"large enough to judge. {int(within.sum())} ({pct(within.mean())}) were within "
            f"0.75-1.5x of the expected bug count, {int((j.regression_ratio > 3).sum())} were above 3x; "
            f"median ratio {j.regression_ratio.median():.2f}.")
        top = j.sort_values("regression_ratio", ascending=False).head(3)
        listing = ", ".join(f"{short(r.repo_full_name)} {r.tag_name} ({r.regression_ratio:.1f}x)"
                            for r in top.itertuples())
        add("releases", "Largest post-release ratios",
            f"{listing}. This is a correlation: a big release draws attention, and attention "
            f"produces bug reports.")

        big = j[j.regression_ratio > 3]
        by_repo = big.groupby("repo_full_name").size().sort_values(ascending=False)
        if len(big):
            spread = ", ".join(f"{short(r)} ({int(c)})" for r, c in by_repo.head(4).items())
            add("releases", f"{len(big)} releases were above 3x the expected bug count",
                f"They come from {len(by_repo)} repositories: {spread}. That is "
                f"{pct(len(big) / len(j), 1)} of the {len(j)} judged releases.")
        else:
            add("releases", "No release was above 3x the expected bug count",
                f"Of {len(j)} judged releases, the highest ratio was {j.regression_ratio.max():.1f}x.")

        g = (j.assign(high=j.regression_ratio > 1.5)
              .groupby("repo_full_name").agg(high=("high", "sum"), total=("high", "size"))
              .query("total >= 3").assign(share=lambda d: d.high / d.total)
              .sort_values(["share", "high"], ascending=False))
        if len(g):
            listing = ", ".join(f"{short(r)} ({int(v.high)} of {int(v.total)})" for r, v in g.head(3).iterrows())
            add("releases", f"{short(g.index[0])} has the highest share of releases above 1.5x",
                f"Repositories with at least 3 judged releases, by how many were above 1.5x the "
                f"expected bug count: {listing}.")

    return pd.DataFrame(rows, columns=["page", "ord", "headline", "text"])


if __name__ == "__main__":
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET TimeZone='UTC'")
    df = build_insights(con)
    for r in df.itertuples():
        print(f"[{r.page} #{r.ord}] {r.headline}\n    {r.text}\n")