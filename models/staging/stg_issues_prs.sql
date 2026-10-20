-- Issues and pull requests from the GitHub GraphQL API. PRIMARY SOURCE.
--
-- Two cleaning jobs happen here and nowhere else:
--   1. Deduplication. The same item appears in several run partitions because
--      it kept being updated; keep the newest version per (repo, kind, number).
--   2. Bot removal. On an active repo dependabot can out-post every human, so
--      leaving bots in makes every downstream metric wrong.
with src as (

    select * from read_parquet('data/raw/issues_prs/**/*.parquet', union_by_name = true)

),

ranked as (

    select
        cast(repo_id as bigint)                     as repo_id,
        kind,
        cast(number as integer)                     as number,
        created_at,
        updated_at,
        closed_at,
        merged_at,
        state,
        author,
        author_association,
        coalesce(labels, '')                        as labels,
        first_response_at,
        row_number() over (
            partition by repo_id, kind, number
            order by updated_at desc
        )                                           as rn
    from src
    where author is not null

)

select
    r.* exclude (rn),
    -- A response before creation is not a real response time. It happens when
    -- an issue is transferred between repositories (comments survive, createdAt
    -- is reset) or converted from a discussion. Null it out rather than letting
    -- a negative value drag the median down.
    case
        when r.first_response_at >= r.created_at
        then date_diff('hour', r.created_at, r.first_response_at)
    end                                                               as response_hours,
    -- Unanswered = no maintainer response within the SLA after creation.
    -- NULL means "not judgeable": the item is still inside its SLA window, or
    -- it was opened by a maintainer (nobody is expected to reply to themselves).
    -- Using a fixed window for every item keeps old and new months comparable.
    case
        when r.author_association in ('OWNER', 'MEMBER', 'COLLABORATOR') then null
        when date_diff('day', r.created_at, {{ as_of() }}) <= {{ var('response_sla_days') }} then null
        when r.first_response_at is null then true
        when r.first_response_at > r.created_at + interval {{ var('response_sla_days') }} day then true
        else false
    end                                                               as is_unresponded,
    r.created_at >= timestamp '{{ var("analysis_start") }}'           as in_window
from ranked r
left join {{ ref('bots') }} b on lower(r.author) = lower(b.login)
where r.rn = 1
  and b.login is null
  and r.author not like '%[bot]'
