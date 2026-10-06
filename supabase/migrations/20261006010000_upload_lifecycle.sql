alter table public.artifacts
    add column status text not null default 'ready'
        check (status in ('pending', 'ready')),
    add column expires_at timestamptz,
    add constraint artifacts_upload_lifecycle_check check (
        (status = 'pending' and expires_at is not null)
        or (status = 'ready' and expires_at is null)
    );

comment on column public.artifacts.status is
    'Whether a direct upload is pending or present with expected declared metadata for downstream validation.';
comment on column public.artifacts.expires_at is
    'Expiry for an unfinished upload; ready artifacts have no upload expiry.';

create policy projects_api_owner_access
on public.projects
for all
using (
    owner_id = nullif(current_setting('app.current_user_id', true), '')::uuid
)
with check (
    owner_id = nullif(current_setting('app.current_user_id', true), '')::uuid
);

create policy artifacts_api_owner_access
on public.artifacts
for all
using (
    exists (
        select 1
        from public.projects
        where projects.id = artifacts.project_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
)
with check (
    exists (
        select 1
        from public.projects
        where projects.id = artifacts.project_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
);

comment on policy projects_api_owner_access on public.projects is
    'Scopes API transactions to the verified JWT subject set in app.current_user_id.';
comment on policy artifacts_api_owner_access on public.artifacts is
    'Scopes artifact access through project ownership for the verified API user.';
