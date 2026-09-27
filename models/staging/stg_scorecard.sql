-- OpenSSF Scorecard: the one signal in this project computed by someone else.
-- Coverage is partial (26/30) because the REST API only serves projects that
-- opted in with publish_results: true. Missing is null, never zero.
with src as (

    select * from read_parquet('data/raw/scorecard/**/*.parquet', union_by_name = true)

),

ranked as (

    select
        cast(repo_id as bigint) as repo_id,
        scorecard_date,
        scorecard_overall,
        check_maintained,
        check_code_review,
        check_vulnerabilities,
        source,
        row_number() over (partition by repo_id order by scorecard_date desc) as rn
    from src
    where repo_id is not null

)

select * exclude (rn) from ranked where rn = 1
