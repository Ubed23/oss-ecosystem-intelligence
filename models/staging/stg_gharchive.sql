-- GH Archive. HISTORICAL ONLY - event fidelity degraded badly through 2026
-- (see ADR 0002), so this feeds the archived-repo backtest and the fidelity
-- exhibit, and no live metric.
with src as (

    select * from read_parquet('data/raw/gharchive/**/*.parquet', union_by_name = true)

),

deduped as (

    -- a backfill range and a daily run can both cover the same date
    select
        cast(event_date as date)    as event_date,
        cast(repo_id as bigint)     as repo_id,
        actor,
        event_type,
        max(cast(n as integer))     as event_count
    from src
    group by 1, 2, 3, 4

)

select d.*
from deduped d
left join {{ ref('bots') }} b on lower(d.actor) = lower(b.login)
where b.login is null
  and d.actor not like '%[bot]'
