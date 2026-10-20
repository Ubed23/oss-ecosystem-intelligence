-- Every weighting scheme must add up to 1, or scores are not on a 0-100 scale.
select 'balanced' as scheme, sum(weight_balanced) as total from {{ ref('score_weights') }} having abs(sum(weight_balanced) - 1) > 0.001
union all
select 'reliability', sum(weight_reliability) from {{ ref('score_weights') }} having abs(sum(weight_reliability) - 1) > 0.001
union all
select 'community', sum(weight_community) from {{ ref('score_weights') }} having abs(sum(weight_community) - 1) > 0.001
