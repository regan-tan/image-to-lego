-- Exposes only the count of worker attempts with an unexpired lease. This is
-- the durable source of truth for in-process paid generation/conversion work.
-- Applying this migration remains a separate, manually reviewed DB operation.
CREATE OR REPLACE FUNCTION public.worker_release_active_attempt_count()
RETURNS integer
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT count(*)::integer
    FROM public.jobs
    WHERE worker_attempt_id IS NOT NULL
      AND worker_lease_expires_at > statement_timestamp();
$$;

COMMENT ON FUNCTION public.worker_release_active_attempt_count() IS
    'Returns only the number of live worker leases for the CI/CD worker-restart gate.';

-- The release workflow receives a login that is a member of this NOLOGIN role.
-- It can call only the aggregate above, not inspect job rows or application data.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'github_release_gate') THEN
        CREATE ROLE github_release_gate NOLOGIN NOINHERIT;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.worker_release_active_attempt_count() FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO github_release_gate;
GRANT EXECUTE ON FUNCTION public.worker_release_active_attempt_count() TO github_release_gate;
