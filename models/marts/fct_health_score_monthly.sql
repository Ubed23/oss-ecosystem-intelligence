-- Monthly health score, so the dashboard can show a trend as well as a snapshot.
--
-- NORMALISED AGAINST THE POOLED HISTORY, not within each month.
-- A percentile rank always averages about 0.5, so ranking repos within a single
-- month pins the portfolio average near a constant: the trend line could never
-- rise or fall. Here every repo-month is ranked against every other repo-month,
-- so if the whole portfolio genuinely improves, the average moves with it.
-- The score therefore means "relative to this ecosystem's last 12 months", which
-- is not the same scale as fct_repo_health_current (30 repos, trailing 90 days).
-- The two will not match, and the dashboard labels them differently.
--
-- Differences from the current snapshot, stated rather than hidden:
--   * bus_factor_50 is a trailing-12-month figure attached to every month, so
--     that component does not vary by month. The trend is driven by the other five.
--   * the community component uses active contributors in the month. Monthly
--     retention cannot be rebuilt without leaning on the left-truncated early
--     months, so a simpler, unbiased proxy is used.
--   * the current calendar month is excluded: a part-month would distort the
--     last point on the line.
with base as (

    select
        repo_id,
        month_start,
        bus_factor_50,
        distinct_pr_authors,
        ttfr_p50_hours,
        unresponded_rate,
        bugs_open_at_month_end,
        active_contributors
    from {{ ref('fct_repo_health_monthly') }}
    where month_start < date_trunc('month', current_date)

),

ranked as (

    select
        repo_id,
        month_start,
        -- higher rank = healthier. Where lower is better the order is flipped.
        -- Nulls are handled per metric, matching fct_repo_health_current:
        -- no merged PRs is genuinely worrying (nulls first = worst); no issues
        -- opened is not (nulls last on a flipped order = best).
        percent_rank() over (order by bus_factor_50 nulls first)               as bus_factor_score,
        percent_rank() over (order by distinct_pr_authors)                     as maintainer_activity_score,
        percent_rank() over (order by ttfr_p50_hours desc nulls last)          as response_time_score,
        percent_rank() over (order by unresponded_rate desc nulls last)        as unresponded_score,
        percent_rank() over (order by bugs_open_at_month_end desc)             as bug_backlog_score,
        percent_rank() over (order by active_contributors)                     as community_activity_score
    from base

),

w as (

    -- Same seed as the snapshot, so changing a weight changes both.
    select
        max(case when component = 'bus_factor_score'            then weight_balanced end) as w_bus,
        max(case when component = 'maintainer_activity_score'   then weight_balanced end) as w_act,
        max(case when component = 'response_time_score'         then weight_balanced end) as w_resp,
        max(case when component = 'unresponded_score'           then weight_balanced end) as w_unresp,
        max(case when component = 'bug_backlog_score'           then weight_balanced end) as w_bug,
        max(case when component = 'contributor_retention_score' then weight_balanced end) as w_comm
    from {{ ref('score_weights') }}

),

scored as (

    select
        r.*,
        round(100 * (
            r.bus_factor_score           * w.w_bus
          + r.maintainer_activity_score  * w.w_act
          + r.response_time_score        * w.w_resp
          + r.unresponded_score          * w.w_unresp
          + r.bug_backlog_score          * w.w_bug
          + r.community_activity_score   * w.w_comm
        ), 1) as health_score
    from ranked r
    cross join w

)

select
    *,
    -- Direction of travel, computed here so Tableau needs no table calculation.
    -- Null for the first six months of the series.
    round(health_score - lag(health_score, 6) over (
        partition by repo_id order by month_start
    ), 1) as score_change_6m
from scored