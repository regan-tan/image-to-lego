-- Durable worker release coordination. Applying this migration is a separately
-- reviewed database operation; it does not enable an Azure deployment.

CREATE TABLE public.worker_release_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    state text NOT NULL CHECK (state IN ('open', 'draining', 'quiescent', 'deploying', 'verifying', 'blocked')),
    release_id uuid,
    controller_id uuid,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    controller_heartbeat_expires_at timestamptz,
    changed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (
        (state = 'open' AND release_id IS NULL AND controller_id IS NULL
         AND controller_heartbeat_expires_at IS NULL)
        OR state <> 'open'
    )
);

INSERT INTO public.worker_release_state (singleton, state)
VALUES (true, 'open')
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE public.worker_release_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id uuid NOT NULL,
    controller_id uuid NOT NULL,
    fencing_token bigint NOT NULL,
    from_state text NOT NULL,
    to_state text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    detail text
);

ALTER TABLE public.worker_release_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.worker_release_audit ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.worker_release_try_acquire_attempt(
    p_job_id uuid,
    p_owner_id uuid,
    p_job_type text,
    p_attempt_id uuid,
    p_lease_seconds integer
)
RETURNS TABLE(status text, attempt_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_max_lease_seconds constant integer := 600;
    v_state text;
    v_attempt_id uuid;
    v_job_exists boolean;
    v_lease_held boolean;
BEGIN
    IF p_job_id IS NULL OR p_owner_id IS NULL OR p_attempt_id IS NULL
       OR p_job_type NOT IN ('reconstruction', 'conversion')
       OR p_lease_seconds IS NULL OR p_lease_seconds <= 0
       OR p_lease_seconds > v_max_lease_seconds THEN
        RAISE EXCEPTION 'Worker attempt parameters are invalid';
    END IF;
    -- All controllers lock this singleton before they inspect live attempts.
    -- Workers acquire the same lock before a job-row lock, which is the required
    -- lock order and closes the receive-to-lease-claim race.
    SELECT state INTO v_state
    FROM public.worker_release_state
    WHERE singleton = true
    FOR UPDATE;

    IF NOT FOUND OR v_state IS NULL THEN
        RAISE EXCEPTION 'Worker release state cannot be proven';
    END IF;
    IF v_state <> 'open' THEN
        RETURN QUERY SELECT 'release_blocked'::text, NULL::uuid;
        RETURN;
    END IF;

    UPDATE public.jobs AS j
    SET status = CASE WHEN p_job_type = 'conversion' THEN 'running' ELSE j.status END,
        worker_attempt_id = p_attempt_id,
        worker_lease_expires_at = statement_timestamp()
            + make_interval(secs => p_lease_seconds)
    FROM public.projects AS p
    WHERE j.id = p_job_id
      AND j.project_id = p.id
      AND p.owner_id = p_owner_id
      AND j.type = p_job_type
      AND j.status IN ('queued', 'running')
      AND (j.worker_attempt_id IS NULL OR j.worker_lease_expires_at <= statement_timestamp())
    RETURNING j.worker_attempt_id INTO v_attempt_id;

    IF v_attempt_id IS NOT NULL THEN
        RETURN QUERY SELECT 'acquired'::text, v_attempt_id;
        RETURN;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.jobs AS j
        JOIN public.projects AS p ON p.id = j.project_id
        WHERE j.id = p_job_id AND p.owner_id = p_owner_id AND j.type = p_job_type
          AND j.status IN ('queued', 'running')
    ) INTO v_job_exists;

    IF NOT v_job_exists THEN
        RETURN QUERY SELECT 'terminal_or_duplicate'::text, NULL::uuid;
        RETURN;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.jobs AS j
        JOIN public.projects AS p ON p.id = j.project_id
        WHERE j.id = p_job_id AND p.owner_id = p_owner_id AND j.type = p_job_type
          AND j.worker_attempt_id IS NOT NULL
          AND j.worker_lease_expires_at > statement_timestamp()
    ) INTO v_lease_held;

    IF v_lease_held THEN
        RETURN QUERY SELECT 'lease_held'::text, NULL::uuid;
        RETURN;
    END IF;

    RAISE EXCEPTION 'Worker attempt for job % reached an unexpected state', p_job_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.worker_release_begin(
    p_release_id uuid,
    p_controller_id uuid,
    p_heartbeat_seconds integer
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_max_heartbeat_seconds constant integer := 3600;
    v_release public.worker_release_state%ROWTYPE;
BEGIN
    IF p_release_id IS NULL OR p_controller_id IS NULL
       OR p_heartbeat_seconds IS NULL OR p_heartbeat_seconds <= 0
       OR p_heartbeat_seconds > v_max_heartbeat_seconds THEN
        RAISE EXCEPTION 'Release controller parameters are invalid';
    END IF;
    SELECT * INTO v_release FROM public.worker_release_state WHERE singleton = true FOR UPDATE;
    IF NOT FOUND OR v_release.state IS NULL THEN
        RAISE EXCEPTION 'Worker release state cannot be proven';
    END IF;
    IF v_release.state = 'open' THEN
        UPDATE public.worker_release_state
        SET state = 'draining', release_id = p_release_id, controller_id = p_controller_id,
            fencing_token = fencing_token + 1,
            controller_heartbeat_expires_at = statement_timestamp()
                + make_interval(secs => p_heartbeat_seconds),
            changed_at = statement_timestamp()
        WHERE singleton = true
        RETURNING * INTO v_release;
        INSERT INTO public.worker_release_audit (
            release_id, controller_id, fencing_token, from_state, to_state, detail
        ) VALUES (p_release_id, p_controller_id, v_release.fencing_token, 'open', 'draining', NULL);
        RETURN v_release.fencing_token;
    END IF;
    IF v_release.release_id = p_release_id AND v_release.controller_id = p_controller_id
       AND v_release.state = 'draining' THEN
        IF v_release.controller_heartbeat_expires_at IS NULL
           OR v_release.controller_heartbeat_expires_at <= statement_timestamp() THEN
            RAISE EXCEPTION 'Release controller heartbeat expired; recovery is required';
        END IF;
        RETURN v_release.fencing_token;
    END IF;
    RAISE EXCEPTION 'Release gate is owned by another controller or requires recovery';
END;
$$;

CREATE OR REPLACE FUNCTION public.worker_release_transition(
    p_release_id uuid,
    p_controller_id uuid,
    p_fencing_token bigint,
    p_to_state text,
    p_detail text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_release public.worker_release_state%ROWTYPE;
    v_active_attempts integer;
    v_unconfirmed_submissions integer;
BEGIN
    SELECT * INTO v_release FROM public.worker_release_state WHERE singleton = true FOR UPDATE;
    IF NOT FOUND OR v_release.state IS NULL THEN
        RAISE EXCEPTION 'Worker release state cannot be proven';
    END IF;
    IF p_release_id IS NULL OR p_controller_id IS NULL OR p_fencing_token IS NULL
       OR p_fencing_token < 0 OR p_to_state IS NULL
       OR p_to_state NOT IN ('open', 'quiescent', 'deploying', 'verifying', 'blocked') THEN
        RAISE EXCEPTION 'Release transition parameters are invalid';
    END IF;
    IF v_release.release_id IS DISTINCT FROM p_release_id
       OR v_release.controller_id IS DISTINCT FROM p_controller_id
       OR v_release.fencing_token IS DISTINCT FROM p_fencing_token THEN
        RAISE EXCEPTION 'Stale or unauthorized release controller';
    END IF;
    IF v_release.controller_heartbeat_expires_at IS NULL
       OR v_release.controller_heartbeat_expires_at <= statement_timestamp() THEN
        RAISE EXCEPTION 'Release controller heartbeat expired; recovery is required';
    END IF;
    IF p_to_state = 'quiescent' AND v_release.state IN ('draining', 'blocked') THEN
        -- An expired lease proves that another worker may recover the job; it does
        -- not prove that the original process (especially a CPU conversion thread)
        -- has stopped. Releasing requires every attempt to clear its durable
        -- marker, so uncertainty is blocked rather than deployed through.
        SELECT count(*) INTO v_active_attempts FROM public.jobs
        WHERE worker_attempt_id IS NOT NULL;
        SELECT count(*) INTO v_unconfirmed_submissions FROM public.jobs
        WHERE type = 'reconstruction' AND status = 'running' AND provider_job_id IS NULL;
        IF v_active_attempts <> 0 OR v_unconfirmed_submissions <> 0 THEN
            RAISE EXCEPTION 'Workers or ambiguous provider submissions are still active';
        END IF;
    ELSIF NOT (
        (v_release.state = 'quiescent' AND p_to_state = 'deploying')
        OR (v_release.state = 'deploying' AND p_to_state = 'verifying')
        OR (p_to_state = 'blocked' AND v_release.state <> 'open')
        OR (v_release.state = 'verifying' AND p_to_state = 'open')
    ) THEN
        RAISE EXCEPTION 'Illegal worker release transition from % to %', v_release.state, p_to_state;
    END IF;

    INSERT INTO public.worker_release_audit (
        release_id, controller_id, fencing_token, from_state, to_state, detail
    ) VALUES (p_release_id, p_controller_id, p_fencing_token, v_release.state, p_to_state, p_detail);

    UPDATE public.worker_release_state
    SET state = p_to_state,
        release_id = CASE WHEN p_to_state = 'open' THEN NULL ELSE release_id END,
        controller_id = CASE WHEN p_to_state = 'open' THEN NULL ELSE controller_id END,
        controller_heartbeat_expires_at = CASE WHEN p_to_state = 'open' THEN NULL ELSE controller_heartbeat_expires_at END,
        changed_at = statement_timestamp()
    WHERE singleton = true;
END;
$$;

CREATE OR REPLACE FUNCTION public.worker_release_recover(
    p_controller_id uuid,
    p_heartbeat_seconds integer,
    p_detail text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_max_heartbeat_seconds constant integer := 3600;
    v_release public.worker_release_state%ROWTYPE;
BEGIN
    IF p_controller_id IS NULL OR p_heartbeat_seconds IS NULL OR p_heartbeat_seconds <= 0
       OR p_heartbeat_seconds > v_max_heartbeat_seconds THEN
        RAISE EXCEPTION 'Release controller parameters are invalid';
    END IF;
    SELECT * INTO v_release FROM public.worker_release_state WHERE singleton = true FOR UPDATE;
    IF NOT FOUND OR v_release.state IS NULL THEN
        RAISE EXCEPTION 'Worker release state cannot be proven';
    END IF;
    IF v_release.state = 'open'
       OR v_release.controller_heartbeat_expires_at > statement_timestamp() THEN
        RAISE EXCEPTION 'Release recovery is not authorized while a controller is healthy';
    END IF;
    UPDATE public.worker_release_state
    SET state = 'blocked', controller_id = p_controller_id, fencing_token = fencing_token + 1,
        controller_heartbeat_expires_at = statement_timestamp() + make_interval(secs => p_heartbeat_seconds),
        changed_at = statement_timestamp()
    WHERE singleton = true
    RETURNING * INTO v_release;
    INSERT INTO public.worker_release_audit (
        release_id, controller_id, fencing_token, from_state, to_state, detail
    ) VALUES (v_release.release_id, p_controller_id, v_release.fencing_token,
              'recovery_required', 'blocked', p_detail);
    RETURN v_release.fencing_token;
END;
$$;

CREATE OR REPLACE FUNCTION public.worker_release_heartbeat(
    p_release_id uuid, p_controller_id uuid, p_fencing_token bigint, p_heartbeat_seconds integer
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_max_heartbeat_seconds constant integer := 3600;
BEGIN
    IF p_release_id IS NULL OR p_controller_id IS NULL OR p_fencing_token IS NULL
       OR p_fencing_token < 0 OR p_heartbeat_seconds IS NULL OR p_heartbeat_seconds <= 0
       OR p_heartbeat_seconds > v_max_heartbeat_seconds THEN
        RAISE EXCEPTION 'Release controller parameters are invalid';
    END IF;
    UPDATE public.worker_release_state
    SET controller_heartbeat_expires_at = statement_timestamp() + make_interval(secs => p_heartbeat_seconds),
        changed_at = statement_timestamp()
    WHERE singleton = true AND release_id = p_release_id AND controller_id = p_controller_id
      AND fencing_token = p_fencing_token AND state <> 'open'
      AND controller_heartbeat_expires_at > statement_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Stale or unauthorized release controller';
    END IF;
END;
$$;

REVOKE ALL ON TABLE public.worker_release_state, public.worker_release_audit FROM PUBLIC;
REVOKE ALL ON FUNCTION public.worker_release_try_acquire_attempt(uuid, uuid, text, uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.worker_release_begin(uuid, uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.worker_release_transition(uuid, uuid, bigint, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.worker_release_heartbeat(uuid, uuid, bigint, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.worker_release_recover(uuid, integer, text) FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'github_release_coordinator') THEN
        CREATE ROLE github_release_coordinator NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'image_to_lego_worker') THEN
        CREATE ROLE image_to_lego_worker NOLOGIN NOINHERIT;
    END IF;
END;
$$;

-- This function changes job state under SECURITY DEFINER. It is deliberately
-- not a Supabase RPC for browser-authenticated users: the worker's private
-- database login must be granted membership in image_to_lego_worker during
-- reviewed deployment configuration.
GRANT USAGE ON SCHEMA public TO image_to_lego_worker;
GRANT EXECUTE ON FUNCTION public.worker_release_try_acquire_attempt(uuid, uuid, text, uuid, integer) TO image_to_lego_worker;
GRANT USAGE ON SCHEMA public TO github_release_coordinator;
GRANT EXECUTE ON FUNCTION public.worker_release_begin(uuid, uuid, integer) TO github_release_coordinator;
GRANT EXECUTE ON FUNCTION public.worker_release_transition(uuid, uuid, bigint, text, text) TO github_release_coordinator;
GRANT EXECUTE ON FUNCTION public.worker_release_heartbeat(uuid, uuid, bigint, integer) TO github_release_coordinator;
GRANT EXECUTE ON FUNCTION public.worker_release_recover(uuid, integer, text) TO github_release_coordinator;

COMMENT ON TABLE public.worker_release_state IS
    'Singleton release gate. It is locked before jobs so draining atomically blocks new leases.';
COMMENT ON FUNCTION public.worker_release_try_acquire_attempt(uuid, uuid, text, uuid, integer) IS
    'Atomically returns acquired, lease_held, terminal_or_duplicate, or release_blocked.';
