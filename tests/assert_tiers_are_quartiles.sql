-- Tiers come from ntile(4), so their sizes may differ by at most one.
select max(c) - min(c) as spread
from (select health_tier, count(*) as c from {{ ref('fct_repo_health_current') }} group by 1)
having max(c) - min(c) > 1
