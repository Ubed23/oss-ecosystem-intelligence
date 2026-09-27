-- Person-actions derived from issues, PRs, comments and reviews.
-- Replaces GH Archive as the cohort input (see ADR 0002).
-- A contribution is work. Stars and forks are interest, and are not here.
with src as (

    select * from read_parquet('data/raw/contributions/**/*.parquet', union_by_name = true)

)

select distinct
    cast(repo_id as bigint)                     as repo_id,
    actor,
    contributed_at,
    contribution_type,
    date_trunc('month', contributed_at)         as contribution_month
from src s
where actor is not null
  and actor not like '%[bot]'
  and not exists (select 1 from {{ ref('bots') }} b where lower(b.login) = lower(s.actor))
