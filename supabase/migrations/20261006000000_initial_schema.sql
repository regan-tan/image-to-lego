create extension if not exists pgcrypto with schema extensions;

create table public.projects (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    name text not null check (length(btrim(name)) > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.jobs (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects (id) on delete cascade,
    type text not null check (type in ('reconstruction', 'conversion')),
    status text not null default 'queued'
        check (status in ('queued', 'running', 'succeeded', 'failed', 'canceled')),
    idempotency_key text not null check (length(btrim(idempotency_key)) > 0),
    provider_job_id text,
    error_code text,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (project_id, type, idempotency_key)
);

create table public.artifacts (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects (id) on delete cascade,
    producer_job_id uuid references public.jobs (id) on delete set null,
    kind text not null check (length(btrim(kind)) > 0),
    blob_name text not null check (length(btrim(blob_name)) > 0),
    mime_type text not null check (length(btrim(mime_type)) > 0),
    size_bytes bigint not null check (size_bytes >= 0),
    sha256 text not null check (sha256 ~ '^[0-9a-fA-F]{64}$'),
    created_at timestamptz not null default now()
);

create table public.reconstruction_runs (
    job_id uuid primary key references public.jobs (id) on delete cascade,
    input_artifact_id uuid not null references public.artifacts (id) on delete restrict,
    provider text not null check (length(btrim(provider)) > 0),
    model text not null check (length(btrim(model)) > 0),
    settings jsonb not null default '{}'::jsonb
        check (jsonb_typeof(settings) = 'object')
);

create table public.conversion_runs (
    job_id uuid primary key references public.jobs (id) on delete cascade,
    source_artifact_id uuid not null references public.artifacts (id) on delete restrict,
    target_parts integer not null check (target_parts > 0),
    up_axis text not null check (up_axis in ('x', 'y', 'z')),
    algorithm_version text not null check (length(btrim(algorithm_version)) > 0),
    settings jsonb not null default '{}'::jsonb
        check (jsonb_typeof(settings) = 'object')
);

create index projects_owner_updated_at_idx
    on public.projects (owner_id, updated_at desc);
create index jobs_project_created_at_idx
    on public.jobs (project_id, created_at desc);
create index jobs_status_created_at_idx
    on public.jobs (status, created_at);
create index artifacts_project_kind_created_at_idx
    on public.artifacts (project_id, kind, created_at desc);

create function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger projects_set_updated_at
before update on public.projects
for each row execute function public.set_updated_at();

create trigger jobs_set_updated_at
before update on public.jobs
for each row execute function public.set_updated_at();

alter table public.projects enable row level security;
alter table public.jobs enable row level security;
alter table public.artifacts enable row level security;
alter table public.reconstruction_runs enable row level security;
alter table public.conversion_runs enable row level security;

comment on table public.projects is
    'Application projects. Access is initially mediated by FastAPI; no browser policies exist.';
comment on table public.jobs is
    'Idempotent reconstruction and conversion job metadata.';
comment on table public.artifacts is
    'Metadata for objects stored in Azure Blob Storage, not Supabase Storage.';

