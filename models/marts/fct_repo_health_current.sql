-- Current health snapshot with the composite score.
--
-- Responsiveness and merge activity are measured over a TRAILING 90 DAYS, not
-- the latest calendar month. A quiet month would otherwise leave those metrics
-- null, and a null percentile rank would score the repo as worst - punishing
-- "no data" as if it were "bad data". 90 days also smooths release cycles.
--
-- Every component is a PERCENTILE RANK within the tracked set. You cannot
-- average a bus factor of 3, 41 hours and 180 open bugs; ranking makes them
-- comparable and makes the claim honest - "relative to this ecosystem", not
-- "objectively healthy".
--
-- Weights live in seeds/score_weights.csv so the score can be recomputed under
-- several schemes (sensitivity analysis) and exposed as Tableau parameters.
with latest as (

    select max(month_start) as month_start from {{ ref('fct_repo_health_monthly') }}

),

recent_response as (

    select
        repo_id,
        median(response_hours)                                           as ttfr_p50_hours,
        quantile_cont(response_hours, 0.9)                               as ttfr_p90_hours,
        count(*)                                                         as items_opened_90d,
        sum(case when is_unresponded then 1 else 0 end) * 1.0 / count(*) as unresponded_rate
    from {{ ref('stg_issues_prs') }}
    where in_window
      and created_at >= current_timestamp - interval 90 day
    group by 1

),

recent_merges as (

    select
        repo_id,
        count(*)                as prs_merged_90d,
        count(distinct author)  as distinct_pr_authors_90d,
        median(time_to_merge_hours) as median_merge_hours
    from {{ ref('int_merged_prs') }}
    where merged_at >= current_timestamp - interval 90 day
    group by 1

),

release_gap as (

    select repo_id, median(gap_days) as median_release_gap_days,
           max(published_at)         as last_release_at
    from (
        select repo_id, published_at,
               date_diff('day', lag(published_at) over (
                   partition by repo_id order by published_at), published_at) as gap_days
        from {{ ref('stg_releases') }}
    ) x
    group by 1

),

base as (

    select
        h.repo_id,
        h.month_start,
        h.bugs_open_at_month_end,
        h.bus_factor_50,
        h.top_author_share,
        h.active_contributors,
        d.repo_full_name, d.ecosystem, d.criticality_tier,
        d.scorecard_overall, d.check_maintained, d.has_scorecard,
        r.ttfr_p50_hours, r.ttfr_p90_hours, r.unresponded_rate,
        coalesce(r.items_opened_90d, 0)        as items_opened_90d,
        coalesce(m.prs_merged_90d, 0)          as prs_merged_90d,
        coalesce(m.distinct_pr_authors_90d, 0) as distinct_pr_authors_90d,
        m.median_merge_hours,
        g.median_release_gap_days,
        date_diff('day', g.last_release_at, current_timestamp) as days_since_release,
        coalesce((
            select avg(c.retention_rate)
            from {{ ref('fct_contributor_cohorts') }} c
            where c.repo_id = h.repo_id and c.months_since = 3
        ), 0) as retention_m3
    from {{ ref('fct_repo_health_monthly') }} h
    join {{ ref('dim_repo') }} d using (repo_id)
    left join recent_response r using (repo_id)
    left join recent_merges m  using (repo_id)
    left join release_gap g    using (repo_id)
    where h.month_start = (select month_start from latest)

),

ranked as (

    select
        *,
        -- higher rank = healthier. Metrics where lower is better are flipped
        -- with desc. nulls last on flipped metrics means "no data" does NOT
        -- score as worst.
        percent_rank() over (order by bus_factor_50 nulls first)              as bus_factor_score,
        percent_rank() over (order by distinct_pr_authors_90d)                as maintainer_activity_score,
        percent_rank() over (order by ttfr_p50_hours desc nulls last)         as response_time_score,
        percent_rank() over (order by unresponded_rate desc nulls last)       as unresponded_score,
        percent_rank() over (order by bugs_open_at_month_end desc nulls last) as bug_backlog_score,
        percent_rank() over (order by retention_m3)                           as contributor_retention_score
    from base

),

w as (

    select
        max(case when component = 'bus_factor_score' then weight_balanced end)            as w_bus,
        max(case when component = 'maintainer_activity_score' then weight_balanced end)   as w_act,
        max(case when component = 'response_time_score' then weight_balanced end)         as w_resp,
        max(case when component = 'unresponded_score' then weight_balanced end)           as w_unresp,
        max(case when component = 'bug_backlog_score' then weight_balanced end)           as w_bug,
        max(case when component = 'contributor_retention_score' then weight_balanced end) as w_ret
    from {{ ref('score_weights') }}

),

scored as (

    select
        r.*,
        round(100 * (
            r.bus_factor_score * w.w_bus
          + r.maintainer_activity_score * w.w_act
          + r.response_time_score * w.w_resp
          + r.unresponded_score * w.w_unresp
          + r.bug_backlog_score * w.w_bug
          + r.contributor_retention_score * w.w_ret
        ), 1) as health_score
    from ranked r cross join w

)

select
    *,
    case ntile(4) over (order by health_score)
        when 1 then 'critical'
        when 2 then 'at_risk'
        when 3 then 'stable'
        else 'healthy'
    end as health_tier
from scored
