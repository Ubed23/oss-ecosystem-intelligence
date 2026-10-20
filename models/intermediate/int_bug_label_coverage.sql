-- How much of each repo's issue traffic carries a bug label.
-- Projects that do not use a "bug" label show tiny bug counts. Percentile
-- ranking would then give them the best backlog score for the wrong reason, so
-- the score treats them as "no usable data" (neutral 0.5) instead.
with issues as (

    select repo_id, count(*) as issues_in_window
    from {{ ref('stg_issues_prs') }}
    where kind = 'issue' and in_window
    group by 1

),

bugs as (

    select repo_id, count(distinct number) as bugs_in_window
    from {{ ref('int_labeled_issues') }}
    where normalized_label in ('bug', 'regression')
      and created_at >= timestamp '{{ var("analysis_start") }}'
    group by 1

)

select
    d.repo_id,
    coalesce(i.issues_in_window, 0)                                   as issues_in_window,
    coalesce(b.bugs_in_window, 0)                                     as bugs_in_window,
    coalesce(b.bugs_in_window, 0) * 1.0 / nullif(i.issues_in_window, 0) as bug_label_share,
    coalesce(coalesce(b.bugs_in_window, 0) * 1.0 / nullif(i.issues_in_window, 0), 0)
        >= {{ var('min_bug_label_share') }}                           as has_bug_labels
from {{ ref('dim_repo') }} d
left join issues i using (repo_id)
left join bugs b using (repo_id)
