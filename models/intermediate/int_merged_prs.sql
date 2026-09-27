-- Merged PRs only, inside the analysis window.
-- The window filter matters: pagination was by updated_at, so pre-window items
-- present in the raw data are only those touched recently - a biased sample.
select
    repo_id,
    author,
    number,
    created_at,
    merged_at,
    date_trunc('month', merged_at)            as merged_month,
    date_diff('hour', created_at, merged_at)  as time_to_merge_hours
from {{ ref('stg_issues_prs') }}
where kind = 'pr'
  and merged_at is not null
  and merged_at >= timestamp '{{ var("analysis_start") }}'
