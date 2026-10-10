import duckdb
con = duckdb.connect("warehouse/oss.duckdb", read_only=True)
con.execute("SET TimeZone='UTC'")

df = con.execute("""
select h.repo_id, h.repo_full_name, h.retention_m3, h.contributor_retention_score,
       h.health_score,
       rank() over (order by h.health_score desc) as health_rank,
       (select count(*) from fct_contributor_cohorts c
         where c.repo_id = h.repo_id and c.months_since = 3) as m3_cohorts,
       (select round(avg(c.cohort_contributors), 1) from fct_contributor_cohorts c
         where c.repo_id = h.repo_id and c.months_since = 3) as avg_cohort_size
from fct_repo_health_current h
order by h.retention_m3, h.repo_id
""").fetchdf()
df.to_csv("docs/retention_after2.csv", index=False)
print(df.to_string(index=False))
print("\nRepos with retention_m3 = 0:", int((df.retention_m3 == 0).sum()))
