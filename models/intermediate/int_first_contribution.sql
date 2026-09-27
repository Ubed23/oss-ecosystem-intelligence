-- First month each person contributed to each repo.
--
-- LEFT-TRUNCATED: "first" means first observed since the analysis start, not
-- first ever. Someone who contributed in 2019 and returned last month looks
-- like a newcomer. Stated in docs/metrics.md and on the dashboard.
select
    repo_id,
    actor,
    min(contribution_month) as cohort_month
from {{ ref('stg_contributions') }}
group by 1, 2
