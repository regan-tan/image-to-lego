-- Deleting a project cascades to its jobs, run rows, and artifacts in one statement. RESTRICT is
-- checked immediately, so it can reject an artifact delete before the same cascade has removed the
-- run row that references it. NO ACTION is checked at the end of the statement: deleting a single
-- artifact that a run still uses is still rejected, but a whole-project cascade succeeds.
alter table public.reconstruction_runs
    drop constraint reconstruction_runs_input_artifact_id_fkey,
    add constraint reconstruction_runs_input_artifact_id_fkey
        foreign key (input_artifact_id) references public.artifacts (id) on delete no action;

alter table public.conversion_runs
    drop constraint conversion_runs_source_artifact_id_fkey,
    add constraint conversion_runs_source_artifact_id_fkey
        foreign key (source_artifact_id) references public.artifacts (id) on delete no action;

-- The Blob sweep must learn which project folders no longer have a project row, across all owners.
-- RLS limits the API role to one owner per transaction, so this narrow SECURITY DEFINER function
-- answers only "which of these IDs still exist" and exposes no other project data.
create function public.existing_project_ids(candidate_ids uuid[])
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
    select id from public.projects where id = any(candidate_ids);
$$;

-- Functions are executable by PUBLIC by default, and Supabase exposes public-schema functions to
-- browser roles through its REST API. Only the provisioned API role may call this one.
revoke execute on function public.existing_project_ids(uuid[]) from public, anon, authenticated;

comment on function public.existing_project_ids(uuid[]) is
    'Returns the subset of candidate project IDs that still exist; used only by the Blob sweep.';
