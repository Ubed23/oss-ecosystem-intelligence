with src as (

    select * from read_parquet('data/raw/releases/**/*.parquet', union_by_name = true)

)

select distinct
    cast(repo_id as bigint) as repo_id,
    tag_name,
    published_at
from src
where published_at is not null
