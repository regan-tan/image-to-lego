-- Worker lease tracking for reconstruction and conversion jobs.
-- Safe for databases where lease columns were added manually.

ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS worker_attempt_id uuid,
    ADD COLUMN IF NOT EXISTS worker_lease_expires_at timestamptz;

CREATE INDEX IF NOT EXISTS jobs_worker_lease_expires_at_idx
    ON public.jobs (worker_lease_expires_at)
    WHERE worker_attempt_id IS NOT NULL;

COMMENT ON COLUMN public.jobs.worker_attempt_id IS
    'Fencing token for the worker attempt currently allowed to change durable job state.';

COMMENT ON COLUMN public.jobs.worker_lease_expires_at IS
    'UTC expiry for the current worker attempt. Expired leases may be safely recovered.';
