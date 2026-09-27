-- Retention triangle. Of the people whose first observed contribution to a
-- repo fell in month M, how many were active again N months later?
--
-- Total contributor count is a vanity metric - it rises with any attention.
-- Retention says whether a project turns newcomers into regulars, which is
-- what determines survival past the current maintainers.
with cohort_size as (

    select repo_id, cohort_month, count(distinct actor) as cohort_contributors
    from {{ ref('int_first_contribution') }}
    group by 1, 2

),

activity as (

    select
        f.repo_id,
        f.cohort_month,
        f.actor,
        date_diff('month', f.cohort_month, c.contribution_month) as months_since
    from {{ ref('int_first_contribution') }} f
    join {{ ref('stg_contributions') }} c
      on f.repo_id = c.repo_id and f.actor = c.actor
    where c.contribution_month > f.cohort_month

)

select
    a.repo_id,
    a.cohort_month,
    a.months_since,
    s.cohort_contributors,
    count(distinct a.actor)                                           as retained_contributors,
    count(distinct a.actor) * 1.0 / nullif(s.cohort_contributors, 0)  as retention_rate
from activity a
join cohort_size s
  on a.repo_id = s.repo_id and a.cohort_month = s.cohort_month
where a.months_since between 1 and 12
group by 1, 2, 3, 4
