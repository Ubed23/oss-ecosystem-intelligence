select repo_id, health_score from {{ ref('fct_repo_health_current') }}
where health_score < 0 or health_score > 100
