-- One row per repo per month. Activity metrics are for that month; bus factor
-- is a trailing-12-month measure attached to every row for trend context.
--
-- Note which CTEs filter on in_window and which do not:
--   responsiveness / merges / bugs_opened  -> RATE metrics, window-filtered
--   backlog                                -> a STOCK metric, deliberately not
with months as (

    select distinct date_trunc('month', created_at) as month_start
    from {{ ref('stg_issues_prs') }}
    where in_window

),

spine as (

    select r.repo_id, m.month_start
    from {{ ref('dim_repo') }} r
    cross join months m

),

responsiveness as (

    select
        repo_id,
        date_trunc('month', created_at)                                  as month_start,
        median(response_hours)                                           as ttfr_p50_hours,
        quantile_cont(response_hours, 0.9)                               as ttfr_p90_hours,
        count(*)                                                         as items_opened,
        sum(case when is_unresponded then 1 else 0 end) * 1.0 / count(*) as unresponded_rate
    from {{ ref('stg_issues_prs') }}
    where in_window
    group by 1, 2

),

merges as (

    select
        repo_id,
        merged_month                 as month_start,
        count(*)                     as prs_merged,
        count(distinct author)       as distinct_pr_authors,
        median(time_to_merge_hours)  as median_merge_hours
    from {{ ref('int_merged_prs') }}
    group by 1, 2

),

bugs_opened as (

    select
        repo_id,
        date_trunc('month', created_at) as month_start,
        count(*)                        as bugs_opened
    from {{ ref('int_labeled_issues') }}
    where normalized_label in ('bug', 'regression')
      and created_at >= timestamp '{{ var("analysis_start") }}'
    group by 1, 2

),

backlog as (

    -- STOCK metric: every bug still open at month end, however old. An issue
    -- from 2019 that is still open is part of today's backlog.
    select
        s.repo_id,
        s.month_start,
        count(*) as bugs_open_at_month_end
    from spine s
    join {{ ref('int_labeled_issues') }} b
      on b.repo_id = s.repo_id
     and b.normalized_label in ('bug', 'regression')
     and b.created_at < s.month_start + interval 1 month
     and (b.closed_at is null or b.closed_at >= s.month_start + interval 1 month)
    group by 1, 2

),

community as (

    select repo_id, contribution_month as month_start, count(distinct actor) as active_contributors
    from {{ ref('stg_contributions') }}
    group by 1, 2

)

select
    s.repo_id,
    s.month_start,
    r.ttfr_p50_hours,
    r.ttfr_p90_hours,
    coalesce(r.items_opened, 0)            as items_opened,
    r.unresponded_rate,
    coalesce(m.prs_merged, 0)              as prs_merged,
    coalesce(m.distinct_pr_authors, 0)     as distinct_pr_authors,
    m.median_merge_hours,
    coalesce(bo.bugs_opened, 0)            as bugs_opened,
    coalesce(bl.bugs_open_at_month_end, 0) as bugs_open_at_month_end,
    coalesce(c.active_contributors, 0)     as active_contributors,
    bf.bus_factor_50,
    bf.top_author_share
from spine s
left join responsiveness r  on s.repo_id = r.repo_id  and s.month_start = r.month_start
left join merges m          on s.repo_id = m.repo_id  and s.month_start = m.month_start
left join bugs_opened bo    on s.repo_id = bo.repo_id and s.month_start = bo.month_start
left join backlog bl        on s.repo_id = bl.repo_id and s.month_start = bl.month_start
left join community c       on s.repo_id = c.repo_id  and s.month_start = c.month_start
left join {{ ref('int_bus_factor') }} bf on s.repo_id = bf.repo_id
