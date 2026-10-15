import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
c.execute("SET TimeZone='UTC'")
print(c.execute("""
select d.repo_full_name, count(*) as releases,
       count(*) filter (where r.expected_bugs >= 2) as judgeable,
       round(median(r.regression_ratio) filter (where r.expected_bugs >= 2), 2) as median_ratio
from fct_release_reliability r join dim_repo d using (repo_id)
where r.published_at <= timestamp '2026-09-18'
group by 1 order by 3 desc
""").fetchdf().to_string(index=False))