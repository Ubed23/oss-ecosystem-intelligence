-- Bus factor (50%): the fewest non-bot authors accounting for at least half of
-- merged PRs in the window.
--
-- Method: give each author their share, sort descending, take a running total,
-- and count how many authors it takes to cross 50%. The author tie-break keeps
-- the result deterministic - without it, ties reorder between runs and the
-- "biggest movers" chart fills with noise.
--
-- Documented blind spot: maintainers who push straight to main never open a PR
-- and are invisible here.
with shares as (

    select
        repo_id,
        author,
        count(*) * 1.0 / sum(count(*)) over (partition by repo_id) as share
    from {{ ref('int_merged_prs') }}
    group by 1, 2

),

cumulative as (

    select
        *,
        sum(share) over (
            partition by repo_id order by share desc, author
            rows unbounded preceding
        ) - share as share_before
    from shares

)

select
    repo_id,
    count(*)                                    as bus_factor_50,
    max(share)                                  as top_author_share,
    count(distinct author)                      as pr_authors_12m
from cumulative
where share_before < 0.5
group by 1
