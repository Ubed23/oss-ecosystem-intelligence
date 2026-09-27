-- A bus factor of zero is impossible: if any PR was merged, someone merged it.
select repo_id, bus_factor_50 from {{ ref('int_bus_factor') }} where bus_factor_50 < 1
