-- A monthly score outside 0-100 means a weight is wrong or a rank is broken.
select repo_id, month_start, health_score
from {{ ref('fct_health_score_monthly') }}
where health_score < 0 or health_score > 100