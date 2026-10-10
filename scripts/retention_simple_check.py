import duckdb
con = duckdb.connect("warehouse/oss.duckdb", read_only=True)
con.execute("SET TimeZone='UTC'")
print(con.execute("""
select d.repo_full_name,
       sum(c.cohort_contributors) as people_at_m3,
       round(sum(c.retained_contributors) * 1.0 / sum(c.cohort_contributors), 3) as weighted_m3
from fct_contributor_cohorts c join dim_repo d using (repo_id)
where c.months_since = 3
group by 1 order by people_at_m3
""").fetchdf().to_string(index=False))