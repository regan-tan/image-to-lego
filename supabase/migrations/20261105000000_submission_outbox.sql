-- Durable publication intents for reconstruction and conversion job messages.
--
-- A dispatcher must call submission_outbox_begin_send immediately before its
-- Service Bus call.  It must not begin that external call until this function
-- succeeds, and it must complete/fail the claim in a separate short database
-- transaction after the Service Bus call.  No database transaction is held
-- while calling Service Bus.

CREATE TABLE public.submission_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL UNIQUE REFERENCES public.jobs (id) ON DELETE CASCADE,
    owner_id uuid NOT NULL,
    message_type text NOT NULL CHECK (message_type IN ('reconstruction_job', 'conversion_job')),
    schema_version integer NOT NULL CHECK (schema_version > 0),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'claimed', 'delivered', 'attention_required')),
    next_attempt_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_attempt_at timestamptz,
    last_error_code text,
    last_error_message text,
    last_error_at timestamptz,
    claimed_by_dispatcher_id uuid,
    claimed_at timestamptz,
    claim_expires_at timestamptz,
    dispatch_fencing_token bigint NOT NULL DEFAULT 0 CHECK (dispatch_fencing_token >= 0),
    send_started_at timestamptz,
    last_send_started_at timestamptz,
    delivered_at timestamptz,
    attention_required_at timestamptz,
    attention_reason text,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (
        (status = 'pending'
         AND claimed_by_dispatcher_id IS NULL AND claimed_at IS NULL
         AND claim_expires_at IS NULL AND send_started_at IS NULL
         AND delivered_at IS NULL AND attention_required_at IS NULL
         AND attention_reason IS NULL)
        OR (status = 'claimed'
            AND claimed_by_dispatcher_id IS NOT NULL AND claimed_at IS NOT NULL
            AND claim_expires_at IS NOT NULL AND delivered_at IS NULL
            AND attention_required_at IS NULL AND attention_reason IS NULL)
        OR (status = 'delivered'
            AND claimed_by_dispatcher_id IS NULL AND claimed_at IS NULL
            AND claim_expires_at IS NULL AND send_started_at IS NULL
            AND delivered_at IS NOT NULL AND attention_required_at IS NULL
            AND attention_reason IS NULL)
        OR (status = 'attention_required'
            AND claimed_by_dispatcher_id IS NULL AND claimed_at IS NULL
            AND claim_expires_at IS NULL AND send_started_at IS NULL
            AND delivered_at IS NULL AND attention_required_at IS NOT NULL
            AND attention_reason IS NOT NULL)
    )
);

CREATE INDEX submission_outbox_pending_claim_idx
    ON public.submission_outbox (next_attempt_at, created_at)
    WHERE status = 'pending';

CREATE INDEX submission_outbox_claim_expires_at_idx
    ON public.submission_outbox (claim_expires_at)
    WHERE status = 'claimed';

ALTER TABLE public.submission_outbox ENABLE ROW LEVEL SECURITY;

CREATE TRIGGER submission_outbox_set_updated_at
BEFORE UPDATE ON public.submission_outbox
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE FUNCTION public.submission_outbox_create(
    p_job_id uuid,
    p_owner_id uuid,
    p_schema_version integer
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_message_type text;
    v_outbox_id uuid;
BEGIN
    IF p_job_id IS NULL OR p_owner_id IS NULL OR p_schema_version IS NULL
       OR p_schema_version <= 0 THEN
        RAISE EXCEPTION 'Submission outbox parameters are invalid';
    END IF;

    SELECT CASE j.type
        WHEN 'reconstruction' THEN 'reconstruction_job'
        WHEN 'conversion' THEN 'conversion_job'
    END
    INTO v_message_type
    FROM public.jobs AS j
    JOIN public.projects AS p ON p.id = j.project_id
    WHERE j.id = p_job_id AND p.owner_id = p_owner_id
      AND j.status = 'queued';

    IF NOT FOUND OR v_message_type IS NULL THEN
        RAISE EXCEPTION 'Queued job ownership cannot be proven for submission outbox';
    END IF;

    INSERT INTO public.submission_outbox (job_id, owner_id, message_type, schema_version)
    VALUES (p_job_id, p_owner_id, v_message_type, p_schema_version)
    ON CONFLICT (job_id) DO UPDATE SET job_id = EXCLUDED.job_id
    RETURNING id INTO v_outbox_id;

    RETURN v_outbox_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_claim(
    p_dispatcher_id uuid,
    p_lease_seconds integer
)
RETURNS TABLE(
    status text,
    outbox_id uuid,
    job_id uuid,
    owner_id uuid,
    message_type text,
    schema_version integer,
    dispatch_fencing_token bigint,
    claim_expires_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_max_lease_seconds constant integer := 600;
    v_release_state text;
BEGIN
    IF p_dispatcher_id IS NULL OR p_lease_seconds IS NULL OR p_lease_seconds <= 0
       OR p_lease_seconds > v_max_lease_seconds THEN
        RAISE EXCEPTION 'Submission outbox claim parameters are invalid';
    END IF;

    -- This is the same singleton lock used by release draining.  Once a
    -- draining transaction commits, no subsequent reservation can be made.
    SELECT state INTO v_release_state
    FROM public.worker_release_state
    WHERE singleton = true
    FOR UPDATE;

    IF NOT FOUND OR v_release_state IS NULL THEN
        RAISE EXCEPTION 'Worker release state cannot be proven';
    END IF;
    IF v_release_state <> 'open' THEN
        RETURN QUERY SELECT 'release_blocked'::text, NULL::uuid, NULL::uuid,
            NULL::uuid, NULL::text, NULL::integer, NULL::bigint, NULL::timestamptz;
        RETURN;
    END IF;

    RETURN QUERY
    WITH candidate AS (
        SELECT o.id
        FROM public.submission_outbox AS o
        WHERE (o.status = 'pending' AND o.next_attempt_at <= statement_timestamp())
           OR (o.status = 'claimed' AND o.send_started_at IS NULL
               AND o.claim_expires_at <= statement_timestamp())
        ORDER BY o.next_attempt_at, o.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ), claimed AS (
        UPDATE public.submission_outbox AS o
        SET status = 'claimed',
            attempt_count = o.attempt_count + 1,
            last_attempt_at = statement_timestamp(),
            claimed_by_dispatcher_id = p_dispatcher_id,
            claimed_at = statement_timestamp(),
            claim_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
            dispatch_fencing_token = o.dispatch_fencing_token + 1,
            send_started_at = NULL,
            attention_required_at = NULL,
            attention_reason = NULL
        FROM candidate
        WHERE o.id = candidate.id
        RETURNING o.id, o.job_id, o.owner_id, o.message_type, o.schema_version,
                  o.dispatch_fencing_token, o.claim_expires_at
    )
    SELECT 'claimed'::text, id, job_id, owner_id, message_type, schema_version,
           dispatch_fencing_token, claim_expires_at
    FROM claimed;

    IF NOT FOUND THEN
        RETURN QUERY SELECT 'empty'::text, NULL::uuid, NULL::uuid, NULL::uuid,
            NULL::text, NULL::integer, NULL::bigint, NULL::timestamptz;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_begin_send(
    p_outbox_id uuid,
    p_dispatcher_id uuid,
    p_dispatch_fencing_token bigint
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_release_state text;
BEGIN
    IF p_outbox_id IS NULL OR p_dispatcher_id IS NULL OR p_dispatch_fencing_token IS NULL
       OR p_dispatch_fencing_token <= 0 THEN
        RAISE EXCEPTION 'Submission outbox send parameters are invalid';
    END IF;

    -- Serializing this transition with worker_release_begin guarantees that a
    -- send either starts before draining commits or is rejected before its
    -- external Service Bus call starts.
    SELECT state INTO v_release_state
    FROM public.worker_release_state
    WHERE singleton = true
    FOR UPDATE;
    IF NOT FOUND OR v_release_state IS NULL THEN
        RAISE EXCEPTION 'Worker release state cannot be proven';
    END IF;
    IF v_release_state <> 'open' THEN
        RETURN false;
    END IF;

    UPDATE public.submission_outbox
    SET send_started_at = statement_timestamp(),
        last_send_started_at = statement_timestamp()
    WHERE id = p_outbox_id AND status = 'claimed'
      AND claimed_by_dispatcher_id = p_dispatcher_id
      AND dispatch_fencing_token = p_dispatch_fencing_token
      AND claim_expires_at > statement_timestamp()
      AND send_started_at IS NULL;

    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_record_delivered(
    p_outbox_id uuid,
    p_dispatcher_id uuid,
    p_dispatch_fencing_token bigint
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    UPDATE public.submission_outbox
    SET status = 'delivered', claimed_by_dispatcher_id = NULL, claimed_at = NULL,
        claim_expires_at = NULL, send_started_at = NULL,
        delivered_at = statement_timestamp(), last_error_code = NULL,
        last_error_message = NULL, last_error_at = NULL
    WHERE id = p_outbox_id AND status = 'claimed'
      AND claimed_by_dispatcher_id = p_dispatcher_id
      AND dispatch_fencing_token = p_dispatch_fencing_token
      AND send_started_at IS NOT NULL;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_record_known_failure(
    p_outbox_id uuid,
    p_dispatcher_id uuid,
    p_dispatch_fencing_token bigint,
    p_error_code text,
    p_error_message text,
    p_retry_at timestamptz
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_error_code IS NULL OR length(btrim(p_error_code)) = 0
       OR p_error_message IS NULL OR p_retry_at IS NULL
       OR p_retry_at < statement_timestamp() THEN
        RAISE EXCEPTION 'Submission outbox failure parameters are invalid';
    END IF;

    UPDATE public.submission_outbox
    SET status = 'pending', next_attempt_at = p_retry_at,
        claimed_by_dispatcher_id = NULL, claimed_at = NULL, claim_expires_at = NULL,
        send_started_at = NULL, last_error_code = p_error_code,
        last_error_message = p_error_message, last_error_at = statement_timestamp()
    WHERE id = p_outbox_id AND status = 'claimed'
      AND claimed_by_dispatcher_id = p_dispatcher_id
      AND dispatch_fencing_token = p_dispatch_fencing_token;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_record_uncertain(
    p_outbox_id uuid,
    p_dispatcher_id uuid,
    p_dispatch_fencing_token bigint,
    p_reason text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_reason IS NULL OR length(btrim(p_reason)) = 0 THEN
        RAISE EXCEPTION 'Submission outbox uncertainty parameters are invalid';
    END IF;

    UPDATE public.submission_outbox
    SET status = 'attention_required', claimed_by_dispatcher_id = NULL, claimed_at = NULL,
        claim_expires_at = NULL, send_started_at = NULL,
        attention_required_at = statement_timestamp(), attention_reason = p_reason,
        last_error_code = 'publication_uncertain', last_error_message = p_reason,
        last_error_at = statement_timestamp()
    WHERE id = p_outbox_id AND status = 'claimed'
      AND claimed_by_dispatcher_id = p_dispatcher_id
      AND dispatch_fencing_token = p_dispatch_fencing_token;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_release_unstarted_claim(
    p_outbox_id uuid,
    p_dispatcher_id uuid,
    p_dispatch_fencing_token bigint
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    UPDATE public.submission_outbox
    SET status = 'pending', next_attempt_at = statement_timestamp(),
        claimed_by_dispatcher_id = NULL, claimed_at = NULL, claim_expires_at = NULL
    WHERE id = p_outbox_id AND status = 'claimed'
      AND claimed_by_dispatcher_id = p_dispatcher_id
      AND dispatch_fencing_token = p_dispatch_fencing_token
      AND send_started_at IS NULL;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_mark_expired_sends_attention()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_updated integer;
BEGIN
    -- Lease expiry never proves the Service Bus operation stopped.  It moves
    -- the intent to a durable, release-blocking reconciliation state instead
    -- of making it eligible for automatic retry.
    UPDATE public.submission_outbox
    SET status = 'attention_required', claimed_by_dispatcher_id = NULL, claimed_at = NULL,
        claim_expires_at = NULL, send_started_at = NULL,
        attention_required_at = statement_timestamp(),
        attention_reason = 'publication claim expired after send began',
        last_error_code = 'publication_uncertain',
        last_error_message = 'publication claim expired after send began',
        last_error_at = statement_timestamp()
    WHERE status = 'claimed' AND send_started_at IS NOT NULL
      AND claim_expires_at <= statement_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated;
END;
$$;

CREATE OR REPLACE FUNCTION public.submission_outbox_publication_counts()
RETURNS TABLE(pending_count bigint, in_flight_count bigint, attention_required_count bigint)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT
        count(*) FILTER (WHERE status = 'pending'),
        count(*) FILTER (WHERE status = 'claimed' AND send_started_at IS NOT NULL),
        count(*) FILTER (WHERE status = 'attention_required')
    FROM public.submission_outbox;
$$;

-- Pending intents are deliberately not a quiescence blocker: no external send
-- has started and they may resume after the release gate reopens.  A send that
-- has started, or whose outcome is uncertain, blocks quiescence until a future
-- controller/reconciliation flow has verified the publisher is stopped and
-- resolved the intent.
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
    v_in_flight_publications integer;
BEGIN
    SELECT * INTO v_release FROM public.worker_release_state WHERE singleton = true FOR UPDATE;
    IF NOT FOUND OR v_release.state IS NULL THEN RAISE EXCEPTION 'Worker release state cannot be proven'; END IF;
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
        SELECT count(*) INTO v_active_attempts FROM public.jobs WHERE worker_attempt_id IS NOT NULL;
        SELECT count(*) INTO v_unconfirmed_submissions FROM public.jobs
        WHERE type = 'reconstruction' AND status = 'running' AND provider_job_id IS NULL;
        SELECT count(*) INTO v_in_flight_publications FROM public.submission_outbox
        WHERE status = 'attention_required'
           OR (status = 'claimed' AND send_started_at IS NOT NULL);
        IF v_active_attempts <> 0 OR v_unconfirmed_submissions <> 0
           OR v_in_flight_publications <> 0 THEN
            RAISE EXCEPTION 'Workers, ambiguous provider submissions, or publications are still active';
        END IF;
    ELSIF NOT (
        (v_release.state = 'quiescent' AND p_to_state = 'deploying')
        OR (v_release.state = 'deploying' AND p_to_state = 'verifying')
        OR (p_to_state = 'blocked' AND v_release.state <> 'open')
        OR (v_release.state = 'verifying' AND p_to_state = 'open')
    ) THEN
        RAISE EXCEPTION 'Illegal worker release transition from % to %', v_release.state, p_to_state;
    END IF;
    INSERT INTO public.worker_release_audit (release_id, controller_id, fencing_token, from_state, to_state, detail)
    VALUES (p_release_id, p_controller_id, p_fencing_token, v_release.state, p_to_state, p_detail);
    UPDATE public.worker_release_state
    SET state = p_to_state,
        release_id = CASE WHEN p_to_state = 'open' THEN NULL ELSE release_id END,
        controller_id = CASE WHEN p_to_state = 'open' THEN NULL ELSE controller_id END,
        controller_heartbeat_expires_at = CASE WHEN p_to_state = 'open' THEN NULL ELSE controller_heartbeat_expires_at END,
        changed_at = statement_timestamp()
    WHERE singleton = true;
END;
$$;

REVOKE ALL ON TABLE public.submission_outbox FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_create(uuid, uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_claim(uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_begin_send(uuid, uuid, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_record_delivered(uuid, uuid, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_record_known_failure(uuid, uuid, bigint, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_record_uncertain(uuid, uuid, bigint, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_release_unstarted_claim(uuid, uuid, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_mark_expired_sends_attention() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.submission_outbox_publication_counts() FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'image_to_lego_outbox_dispatcher') THEN
        CREATE ROLE image_to_lego_outbox_dispatcher NOLOGIN NOINHERIT;
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA public TO image_to_lego_submission, image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_create(uuid, uuid, integer) TO image_to_lego_submission;
GRANT EXECUTE ON FUNCTION public.submission_outbox_claim(uuid, integer) TO image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_begin_send(uuid, uuid, bigint) TO image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_record_delivered(uuid, uuid, bigint) TO image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_record_known_failure(uuid, uuid, bigint, text, text, timestamptz) TO image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_record_uncertain(uuid, uuid, bigint, text) TO image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_release_unstarted_claim(uuid, uuid, bigint) TO image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_mark_expired_sends_attention() TO image_to_lego_outbox_dispatcher;
GRANT EXECUTE ON FUNCTION public.submission_outbox_publication_counts() TO image_to_lego_outbox_dispatcher, github_release_coordinator;

COMMENT ON TABLE public.submission_outbox IS
    'Durable, idempotent Service Bus publication intents. Claimed sends are not automatically retried after their send begins.';
COMMENT ON FUNCTION public.submission_outbox_claim(uuid, integer) IS
    'Reserves one pending publication while the release gate is open; claimed, empty, or release_blocked.';
COMMENT ON FUNCTION public.submission_outbox_begin_send(uuid, uuid, bigint) IS
    'Must succeed immediately before Service Bus send; serializes send start with release draining.';
COMMENT ON FUNCTION public.submission_outbox_mark_expired_sends_attention() IS
    'Expired post-send claims require reconciliation; expiry is never evidence that external publication stopped.';
