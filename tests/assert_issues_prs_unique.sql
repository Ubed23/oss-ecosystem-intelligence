-- The deduplication in stg_issues_prs is the single most likely place for a
-- silent bug: a broken window function doubles every count downstream.
select repo_id, kind, number, count(*) as n
from {{ ref('stg_issues_prs') }}
group by 1, 2, 3
having count(*) > 1
