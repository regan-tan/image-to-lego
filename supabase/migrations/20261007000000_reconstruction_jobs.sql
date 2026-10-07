create unique index artifacts_reconstructed_model_per_job_idx
    on public.artifacts (producer_job_id)
    where kind = 'reconstructed_model';

create policy jobs_api_owner_access
on public.jobs
for all
using (
    exists (
        select 1
        from public.projects
        where projects.id = jobs.project_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
)
with check (
    exists (
        select 1
        from public.projects
        where projects.id = jobs.project_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
);

create policy reconstruction_runs_api_owner_access
on public.reconstruction_runs
for all
using (
    exists (
        select 1
        from public.jobs
        join public.projects on projects.id = jobs.project_id
        where jobs.id = reconstruction_runs.job_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
)
with check (
    exists (
        select 1
        from public.jobs
        join public.projects on projects.id = jobs.project_id
        where jobs.id = reconstruction_runs.job_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
);

comment on index public.artifacts_reconstructed_model_per_job_idx is
    'Makes duplicate generation deliveries reuse one canonical reconstruction artifact.';
