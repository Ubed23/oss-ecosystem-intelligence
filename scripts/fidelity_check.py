import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
c.execute("SET TimeZone='UTC'")
print(c.execute("describe fct_source_fidelity").fetchdf()[["column_name", "column_type"]].to_string(index=False))
print(c.execute("select * from fct_source_fidelity order by 1").fetchdf().to_string(index=False))