# ADR 0004: Maintainers are identified by merged pull requests

Status: accepted, 20 Oct 2026

## Context

Response time and unanswered share count a reply only if it comes from a
maintainer. The first version trusted GitHub's `authorAssociation`: OWNER,
MEMBER or COLLABORATOR.

That label is only OWNER/MEMBER for people whose organisation membership is
public. Core maintainers with private membership appear as CONTRIBUTOR. The
data showed the symptom: repositories such as dask, dagster, plotly and sqlfluff
had 94-100% of items "unanswered" and almost no items authored by a
maintainer. The metric was partly measuring whether a project's maintainers
made their membership public.

## Decision

A maintainer of a repository is anyone who

1. merged a pull request in it (merging needs write access), or
2. is labelled OWNER, MEMBER or COLLABORATOR on something they opened.

The pull stores `mergedBy` and the raw list of first responders
(`login@timestamp`). Which responders count as maintainers is decided in dbt
(`int_maintainers`, `int_item_responses`), so the definition can change without
re-pulling from GitHub.

## Consequences

- Response metrics no longer depend on whether organisation membership is public.
- A drive-by reviewer who never merged is not counted. That is deliberate: the
  question is whether the people who can act on an issue respond.
- Rows pulled before this change have no `merged_by` or responder list and fall
  back to the label rule until they are re-pulled. Until the full re-pull is run
  the old limitation still applies to them.
- Only the first 10 comments and 5 reviews per item are fetched. `comments_total`
  and `reviews_total` are stored so the truncation rate can be measured.
