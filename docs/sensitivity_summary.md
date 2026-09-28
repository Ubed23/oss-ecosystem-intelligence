# Sensitivity analysis

Recomputed the health score under 3 weighting schemes (balanced, reliability, community) defined in `seeds/score_weights.csv`.

## Rank correlation

| scheme A | scheme B | Spearman |
|---|---|---|
| balanced | reliability | 0.945 |
| balanced | community | 0.858 |
| reliability | community | 0.692 |

## Tier stability

**12 of 30 repositories (40%)** keep the same quartile tier under all 3 weightings.

**4** are in the bottom tier under every weighting - these are the findings that do not depend on how the score is configured.

## Interpretation

The ranking moves substantially with the weights. The score should be read as one input among several, not a verdict, and the dashboard exposes the weights as parameters so a viewer can apply their own priorities.

Per-repository detail: `docs/sensitivity.csv`.