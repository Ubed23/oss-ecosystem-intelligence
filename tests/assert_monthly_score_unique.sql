-- One row per repo per month. A duplicate means a join multiplied rows upstream.
select repo_id, month_start, count(*) as n
from {{ ref('fct_health_score_monthly') }}
group by 1, 2
having count(*) > 1