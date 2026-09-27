-- One row per tracked repository. Joined on repo_id everywhere, never on name:
-- three of thirty repos were renamed or transferred during the window.
select
    r.repo_id,
    r.repo_full_name,
    r.package_name,
    r.ecosystem,
    r.category,
    r.criticality_tier,
    s.scorecard_overall,
    s.check_maintained,
    s.check_code_review,
    s.scorecard_date,
    s.repo_id is not null as has_scorecard
from {{ ref('repos') }} r
left join {{ ref('stg_scorecard') }} s using (repo_id)
where r.repo_id is not null
