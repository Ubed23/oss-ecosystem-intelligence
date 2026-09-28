"""Sensitivity analysis: does the ranking survive changing the weights?

    python scripts/sensitivity_analysis.py

The obvious objection to any composite score is "your weights are arbitrary".
They are - until you test them. This recomputes the score under all three
schemes in seeds/score_weights.csv and reports two numbers:

  * Spearman rank correlation between the three rankings
  * the share of repositories that stay in the same quartile tier under all
    three

High stability means the weights barely matter and the signal is in the data.
Low stability means the score is fragile and must be presented as one input
among several rather than a verdict. Either result is publishable; hiding the
question is not.

Outputs docs/sensitivity.csv and docs/sensitivity_summary.md.
"""
import itertools
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "warehouse" / "oss.duckdb"
WEIGHTS = ROOT / "seeds" / "score_weights.csv"
OUT_CSV = ROOT / "docs" / "sensitivity.csv"
OUT_MD = ROOT / "docs" / "sensitivity_summary.md"

COMPONENTS = [
    "bus_factor_score", "maintainer_activity_score", "response_time_score",
    "unresponded_score", "bug_backlog_score", "contributor_retention_score",
]
TIERS = ["critical", "at_risk", "stable", "healthy"]


def tier_of(scores: pd.Series) -> pd.Series:
    """Quartiles of the tracked set - the same rule the dbt model uses."""
    return pd.qcut(scores.rank(method="first"), 4, labels=TIERS)


def main() -> None:
    if not DB.exists():
        raise SystemExit("warehouse/oss.duckdb not found. Run dbt build first.")

    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(f"""
        select repo_full_name, criticality_tier, health_score as score_as_built,
               {', '.join(COMPONENTS)}
        from fct_repo_health_current
    """).df()

    w = pd.read_csv(WEIGHTS).set_index("component")
    schemes = [c for c in w.columns if c.startswith("weight_")]

    for scheme in schemes:
        name = scheme.replace("weight_", "")
        weights = w[scheme]
        if abs(weights.sum() - 1.0) > 0.001:
            print(f"warning: {name} weights sum to {weights.sum():.3f}, not 1.0")
        df[f"score_{name}"] = sum(df[c] * weights[c] for c in COMPONENTS) * 100
        df[f"tier_{name}"] = tier_of(df[f"score_{name}"])
        df[f"rank_{name}"] = df[f"score_{name}"].rank(ascending=False).astype(int)

    names = [s.replace("weight_", "") for s in schemes]

    # --- rank correlation between every pair of schemes ---
    print("Spearman rank correlation between weighting schemes")
    print("(1.00 = identical ranking, 0 = unrelated)\n")
    corrs = []
    for a, b in itertools.combinations(names, 2):
        rho = df[f"score_{a}"].corr(df[f"score_{b}"], method="spearman")
        corrs.append({"scheme_a": a, "scheme_b": b, "spearman": round(rho, 3)})
        print(f"  {a:<12} vs {b:<12}  {rho:.3f}")

    # --- tier stability ---
    tier_cols = [f"tier_{n}" for n in names]
    df["tier_stable"] = df[tier_cols].nunique(axis=1) == 1
    stability = df.tier_stable.mean()
    print(f"\nTier stability: {df.tier_stable.sum()}/{len(df)} "
          f"({stability:.0%}) keep the same tier under all {len(names)} schemes")

    # --- who moves, and how far ---
    rank_cols = [f"rank_{n}" for n in names]
    df["rank_spread"] = df[rank_cols].max(axis=1) - df[rank_cols].min(axis=1)
    movers = df.nlargest(5, "rank_spread")[["repo_full_name", "rank_spread"] + rank_cols]
    print("\nMost weight-sensitive repositories (rank positions moved):")
    print(movers.to_string(index=False))

    # --- who is at risk regardless of weighting: the robust finding ---
    worst = df[df[tier_cols].eq("critical").all(axis=1)]
    print(f"\nCritical under EVERY weighting ({len(worst)}):")
    if worst.empty:
        print("  none - no repository is unambiguously worst")
    else:
        print(worst[["repo_full_name", "criticality_tier"] + [f"score_{n}" for n in names]]
              .round(1).to_string(index=False))

    OUT_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    lines = [
        "# Sensitivity analysis", "",
        f"Recomputed the health score under {len(names)} weighting schemes "
        f"({', '.join(names)}) defined in `seeds/score_weights.csv`.", "",
        "## Rank correlation", "",
        "| scheme A | scheme B | Spearman |", "|---|---|---|",
    ]
    lines += [f"| {c['scheme_a']} | {c['scheme_b']} | {c['spearman']} |" for c in corrs]
    lines += [
        "", "## Tier stability", "",
        f"**{df.tier_stable.sum()} of {len(df)} repositories ({stability:.0%})** keep the "
        f"same quartile tier under all {len(names)} weightings.", "",
        f"**{len(worst)}** are in the bottom tier under every weighting - these are the "
        "findings that do not depend on how the score is configured.", "",
        "## Interpretation", "",
        ("The ranking is robust to how the components are weighted, so the signal is in "
         "the data rather than in the configuration."
         if stability >= 0.7 else
         "The ranking moves substantially with the weights. The score should be read as "
         "one input among several, not a verdict, and the dashboard exposes the weights "
         "as parameters so a viewer can apply their own priorities."), "",
        "Per-repository detail: `docs/sensitivity.csv`.",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT_CSV.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()