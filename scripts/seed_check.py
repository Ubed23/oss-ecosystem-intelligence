import duckdb
c = duckdb.connect("warehouse/oss.duckdb", read_only=True)
for t in ("label_map", "bots", "repos", "score_weights", "backtest_repos"):
    try:
        print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
    except Exception as e:
        print(t, "MISSING:", str(e)[:60])