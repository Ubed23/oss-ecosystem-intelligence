# Backtest

**Observation date** 2024-12-31. Features from activity in 2024-01-01 to 2024-12-31. Label: archived, or no push for 12+ months, as of today.

- Repositories: **243**
- Died since T0: **4** (base rate 1.6%)
- Flagged (bottom quartile of activity score): **61**

| | died | survived |
|---|---|---|
| flagged | 2 | 59 |
| not flagged | 2 | 180 |

- **Precision 3.3%** - of repositories flagged, this share died
- **Recall 50.0%** - of repositories that died, this share was flagged
- **Lift 1.99x** over the 1.6% base rate
- **Median lead time 10.9 months**

## Limitations

1. Activity metrics only. Response times, merge status and labels cannot be
   reconstructed for 2024 because GitHub stripped those fields from event
   payloads in October 2025. The live model uses more signal than this test,
   so these numbers are a floor rather than a ceiling.
2. Death is a proxy: archived now, or silent for 12+ months. Dormancy is not
   archival, and the two are counted separately in `docs/backtest.csv`.
3. Survivorship: the candidate set comes from currently-listed PyPI packages,
   so packages deleted outright are absent.