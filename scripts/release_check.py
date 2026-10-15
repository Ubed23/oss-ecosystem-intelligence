import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
c.execute("SET TimeZone='UTC'")
print(c.execute("describe fct_release_reliability").fetchdf()[["column_name", "column_type"]].to_string(index=False))
print(c.execute("""
select count(*) as releases,
       count(regression_ratio) as with_ratio,
       count(*) filter (where expected_bugs >= 2) as expected_2_plus,
       min(published_at)::date as first_release,
       max(published_at)::date as last_release
from fct_release_reliability""").fetchdf().to_string(index=False))
print(c.execute("select min(created_at)::date as first_issue, max(created_at)::date as last_issue from stg_issues_prs").fetchdf().to_string(index=False))