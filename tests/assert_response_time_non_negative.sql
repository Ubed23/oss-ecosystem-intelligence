-- A negative response time means a reply landed before the issue was opened -
-- always a timezone or join bug.
select repo_id, kind, number, response_hours
from {{ ref('int_item_responses') }} where response_hours < 0
