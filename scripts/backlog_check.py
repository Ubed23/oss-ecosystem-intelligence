import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
c.execute("SET TimeZone='UTC'")
print(c.execute("""
select month_start::date as month, sum(bugs_opened) as opened,
       sum(bugs_open_at_month_end) as open_at_end
from fct_repo_health_monthly group by 1 order by 1
""").fetchdf().to_string(index=False))