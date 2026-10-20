with last_month as (
    select max(contribution_month) as last_month
    from {{ ref('stg_contributions') }}
),

cohort_size as (
    select repo_id, cohort_month, count(distinct actor) as cohort_contributors
    from {{ ref('int_first_contribution') }}
    where cohort_month >= timestamp '{{ var("first_cohort_month") }}'
    group by 1, 2
),

grid as (
    select s.repo_id, s.cohort_month, s.cohort_contributors, m.months_since
    from cohort_size s
    cross join range(0, 13) as m(months_since)
    cross join last_month l
    where s.cohort_month + to_months(m.months_since) < l.last_month
),

retained as (
    select
        f.repo_id,
        f.cohort_month,
        date_diff('month', f.cohort_month, c.contribution_month) as months_since,
        count(distinct f.actor) as retained_contributors
    from {{ ref('int_first_contribution') }} f
    join {{ ref('stg_contributions') }} c
      on f.repo_id = c.repo_id and f.actor = c.actor
    cross join last_month l
    where c.contribution_month > f.cohort_month
      and c.contribution_month < l.last_month
    group by 1, 2, 3
)

select
    g.repo_id,
    g.cohort_month,
    g.months_since,
    g.cohort_contributors,
    case when g.months_since = 0 then g.cohort_contributors
         else coalesce(r.retained_contributors, 0) end                  as retained_contributors,
    case when g.months_since = 0 then 1.0
         else coalesce(r.retained_contributors, 0) * 1.0
              / nullif(g.cohort_contributors, 0) end                    as retention_rate
from grid g
left join retained r
  on  g.repo_id = r.repo_id
  and g.cohort_month = r.cohort_month
  and g.months_since = r.months_since