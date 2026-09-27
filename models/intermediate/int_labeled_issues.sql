-- Labels are a per-project vocabulary: "bug", "type: bug", "kind/bug",
-- "defect". seeds/label_map.csv normalises them. Unmapped labels are dropped
-- rather than guessed - a project that does not label bugs shows zero, which
-- is why the dashboard pairs bug counts with total open issues.
with exploded as (

    select
        i.repo_id,
        i.number,
        i.kind,
        i.created_at,
        i.closed_at,
        i.state,
        trim(lower(label)) as raw_label
    from {{ ref('stg_issues_prs') }} i,
         unnest(string_split(i.labels, '|')) as t(label)
    where i.labels <> ''

)

select distinct
    e.repo_id,
    e.number,
    e.kind,
    e.created_at,
    e.closed_at,
    e.state,
    m.normalized_label
from exploded e
join {{ ref('label_map') }} m
  on e.raw_label = lower(m.raw_label_pattern)
