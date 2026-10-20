-- One row per issue or PR with its first MAINTAINER response.
--
-- `responders` is a ';'-separated list of login@timestamp for the first
-- comments and reviews on the item (author and bots already removed at pull
-- time). The first one written by a maintainer of that repo (int_maintainers)
-- is the first response. Rows pulled before `responders` existed fall back to
-- the association-based first_response_at stored at pull time.
with items as (

    select repo_id, kind, number, author, created_at, in_window,
           first_response_at as legacy_first_response_at, responders
    from {{ ref('stg_issues_prs') }}

),

parsed as (

    select
        i.repo_id, i.kind, i.number, i.author,
        lower(split_part(r.entry, '@', 1))                        as login,
        try_cast(split_part(r.entry, '@', 2) as timestamptz)      as responded_at
    from items i,
         unnest(string_split(i.responders, ';')) as r(entry)
    where i.responders is not null and i.responders <> ''

),

maintainer_response as (

    select p.repo_id, p.kind, p.number, min(p.responded_at) as responded_at
    from parsed p
    join {{ ref('int_maintainers') }} m
      on m.repo_id = p.repo_id and m.login = p.login
    where p.login <> lower(p.author)
    group by 1, 2, 3

),

resolved as (

    select
        i.repo_id, i.kind, i.number, i.created_at, i.in_window,
        case when i.responders is not null
             then mr.responded_at
             else i.legacy_first_response_at
        end                                                       as first_response_at,
        (m.login is not null)                                     as opened_by_maintainer
    from items i
    left join maintainer_response mr
      on mr.repo_id = i.repo_id and mr.kind = i.kind and mr.number = i.number
    left join {{ ref('int_maintainers') }} m
      on m.repo_id = i.repo_id and m.login = lower(i.author)

)

select
    repo_id, kind, number, created_at, in_window, first_response_at,
    opened_by_maintainer,
    -- A response before creation is not a real response time. It happens when
    -- an issue is transferred between repositories or converted from a
    -- discussion. Null it rather than let a negative value drag the median down.
    case
        when first_response_at >= created_at
        then date_diff('hour', created_at, first_response_at)
    end                                                           as response_hours,
    -- Unanswered = no maintainer response within the SLA after creation.
    -- NULL means "not judgeable": still inside the SLA window, or opened by a
    -- maintainer (nobody is expected to reply to themselves). A fixed window for
    -- every item keeps old and recent months comparable.
    case
        when opened_by_maintainer then null
        when date_diff('day', created_at, {{ as_of() }}) <= {{ var('response_sla_days') }} then null
        when first_response_at is null then true
        when first_response_at > created_at + interval {{ var('response_sla_days') }} day then true
        else false
    end                                                           as is_unresponded
from resolved
