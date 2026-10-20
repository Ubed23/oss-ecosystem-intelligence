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
        cast(merged_by as varchar)                  as merged_by,
        cast(responders as varchar)                 as responders,
        cast(comments_total as bigint)              as comments_total,
        cast(reviews_total as bigint)               as reviews_total,
        row_number() over (
            partition by repo_id, kind, number
            -- ties (same updated_at) prefer the richer row: one pulled with the
            -- responder list and merger identity beats an older or lighter one
            order by updated_at desc, (responders is not null) desc,
                     (merged_by is not null) desc, comments_total desc nulls last
        )                                           as rn
    from src
    where author is not null

)

select
    r.* exclude (rn),
    -- Response time and unanswered flags are derived in int_item_responses,
    -- because they need to know who the maintainers are (int_maintainers).
    r.created_at >= timestamp '{{ var("analysis_start") }}'           as in_window
from ranked r
left join {{ ref('bots') }} b on lower(r.author) = lower(b.login)
where r.rn = 1
  and b.login is null
  and r.author not like '%[bot]'
