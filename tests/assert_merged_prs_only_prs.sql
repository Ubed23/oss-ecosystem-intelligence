-- merged_at on an issue means the GraphQL flattening leaked a field.
select repo_id, number from {{ ref('stg_issues_prs') }}
where kind = 'issue' and merged_at is not null
