-- One bot left in makes every contributor metric wrong.
select actor from {{ ref('stg_contributions') }} where actor like '%[bot]%'
union all
select author from {{ ref('stg_issues_prs') }} where author like '%[bot]%'
