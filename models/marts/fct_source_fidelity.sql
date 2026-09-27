-- Dashboard exhibit, not a metric: GH Archive against the authoritative API,
-- month by month. This is the evidence behind ADR 0002 and it belongs on the
-- methodology dashboard rather than in a footnote.
with archive as (

    select
        date_trunc('month', event_date) as month_start,
        sum(event_count)                as archive_events
    from {{ ref('stg_gharchive') }}
    group by 1

),

api as (

    select
        date_trunc('month', created_at) as month_start,
        count(*)                        as api_items_created
    from {{ ref('stg_issues_prs') }}
    where in_window
    group by 1

)

select
    coalesce(a.month_start, b.month_start) as month_start,
    a.archive_events,
    b.api_items_created,
    a.archive_events * 1.0 / nullif(b.api_items_created, 0) as archive_to_api_ratio
from archive a
full outer join api b on a.month_start = b.month_start
order by 1
