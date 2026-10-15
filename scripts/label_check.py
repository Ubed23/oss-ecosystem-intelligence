import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
print(c.execute("""
select kind, count(*) as bug_items
from int_labeled_issues
where normalized_label = 'bug'
group by 1
""").fetchdf().to_string(index=False))
print(c.execute("select distinct kind from stg_issues_prs").fetchdf().to_string(index=False))
