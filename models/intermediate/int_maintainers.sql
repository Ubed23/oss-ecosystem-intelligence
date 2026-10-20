-- Who counts as a maintainer, per repository.
--
-- GitHub's author_association says OWNER / MEMBER / COLLABORATOR only for people
-- whose organisation membership is public. A core maintainer with private
-- membership shows up as CONTRIBUTOR, and relying on that label alone makes a
-- well-run project look unresponsive.
--
-- So a maintainer here is anyone who either
--   * merged a pull request in the repo (merging needs write access), or
--   * is labelled OWNER / MEMBER / COLLABORATOR on something they opened.
-- merged_by is only present in data pulled after the mergedBy change; older
-- rows contribute through the association rule alone.
select distinct repo_id, lower(merged_by) as login
from {{ ref('stg_issues_prs') }}
where kind = 'pr'
  and merged_by is not null
  and merged_by not like '%[bot]'
  and lower(merged_by) not in (select lower(login) from {{ ref('bots') }})

union

select distinct repo_id, lower(author) as login
from {{ ref('stg_issues_prs') }}
where author_association in ('OWNER', 'MEMBER', 'COLLABORATOR')
