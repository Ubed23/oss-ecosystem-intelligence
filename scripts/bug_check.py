import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
c.execute("SET TimeZone='UTC'")
print(c.execute("""
select d.repo_full_name,
       sum(m.bugs_opened) as opened_12m,
       max(case when m.month_start = timestamp '2026-09-01' then m.bugs_open_at_month_end end) as open_sep26
from fct_repo_health_monthly m join dim_repo d using (repo_id)
group by 1 order by 2
""").fetchdf().to_string(index=False))