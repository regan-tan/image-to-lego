create unique index artifacts_lego_model_per_job_idx
    on public.artifacts (producer_job_id)
    where kind = 'lego_model';

create policy conversion_runs_api_owner_access
on public.conversion_runs
for all
using (
    exists (
        select 1
        from public.jobs
        join public.projects on projects.id = jobs.project_id
        where jobs.id = conversion_runs.job_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
)
with check (
    exists (
        select 1
        from public.jobs
        join public.projects on projects.id = jobs.project_id
        where jobs.id = conversion_runs.job_id
          and projects.owner_id =
              nullif(current_setting('app.current_user_id', true), '')::uuid
    )
);

comment on index public.artifacts_lego_model_per_job_idx is
    'Makes duplicate conversion deliveries reuse one canonical LEGO model artifact.';
