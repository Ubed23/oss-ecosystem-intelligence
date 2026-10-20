-- Post-release regression ratio: bugs opened in the N days after a release,
-- against what the prior 90 days' rate would predict.
--
-- Correlation, not causation: a big release draws attention, and attention
-- produces reports. Say so on the dashboard rather than implying the release
-- caused the bugs.
with releases as (

    select repo_id, tag_name, published_at
    from {{ ref('stg_releases') }}
    where published_at >= timestamp '{{ var("analysis_start") }}'

),

bugs as (

    -- distinct: an issue carrying two bug labels must count once
    select distinct repo_id, number, created_at
    from {{ ref('int_labeled_issues') }}
    where normalized_label in ('bug', 'regression')

),

windowed as (

    select
        rel.repo_id,
        rel.tag_name,
        rel.published_at,
        count(b.created_at) filter (
            where b.created_at >= rel.published_at
              and b.created_at <  rel.published_at + interval {{ var('release_window_days') }} day
        ) as bugs_after,
        count(b.created_at) filter (
            where b.created_at <  rel.published_at
              and b.created_at >= rel.published_at - interval {{ var('release_baseline_days') }} day
        ) as bugs_baseline
    from releases rel
    left join bugs b on rel.repo_id = b.repo_id
    group by 1, 2, 3

)

select
    *,
    bugs_baseline * 1.0
        * {{ var('release_window_days') }} / {{ var('release_baseline_days') }} as expected_bugs,
    bugs_after / nullif(
        bugs_baseline * 1.0
        * {{ var('release_window_days') }} / {{ var('release_baseline_days') }}, 0
    ) as regression_ratio,
    -- the follow-up window has fully elapsed within the data we hold
    cast(published_at as date) + {{ var('release_window_days') }}
        <= (select cast(max(created_at) as date) from {{ ref('stg_issues_prs') }}) as window_complete
from windowed
