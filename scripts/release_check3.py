import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
c.execute("SET TimeZone='UTC'")
print(c.execute("""
select d.repo_full_name, r.tag_name, r.published_at::date as published,
       r.bugs_baseline, round(r.expected_bugs, 1) as expected, r.bugs_after
from fct_release_reliability r join dim_repo d using (repo_id)
where d.repo_full_name in ('dask/dask','snowflakedb/snowflake-connector-python')
  and r.expected_bugs >= 2
order by 1, 3
""").fetchdf().to_string(index=False))