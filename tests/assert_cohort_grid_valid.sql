select c.*
from {{ ref('fct_contributor_cohorts') }} c
cross join (select max(contribution_month) as last_month
            from {{ ref('stg_contributions') }}) l
where c.retention_rate < 0
   or c.retention_rate > 1
   or (c.months_since = 0 and c.retention_rate <> 1)
   or c.cohort_month + to_months(c.months_since) >= l.last_month