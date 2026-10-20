-- The snapshot must read a complete month, never the current partial one.
select repo_id
from {{ ref('fct_repo_health_current') }}
where month_start >= date_trunc('month', cast({{ as_of() }} as date))
