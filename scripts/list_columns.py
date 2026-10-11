import duckdb
con = duckdb.connect("warehouse/oss.duckdb", read_only=True)
for t in ("fct_repo_health_monthly", "fct_contributor_cohorts"):
    cols = [r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_name = ?", [t]).fetchall()]
    print(t, "->", cols)