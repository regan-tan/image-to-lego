-- Remove browser execution paths from internal SECURITY DEFINER protocols.
--
-- Each function below is owned by postgres and changes or exposes internal
-- submission, worker, dispatcher, or release-controller state.  Browser roles
-- must not be able to invoke them through PostgREST/Supabase RPC.

REVOKE EXECUTE ON FUNCTION public.worker_release_active_attempt_count() FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.worker_release_try_acquire_attempt(uuid, uuid, text, uuid, integer) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.worker_release_begin(uuid, uuid, integer) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.worker_release_transition(uuid, uuid, bigint, text, text) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.worker_release_recover(uuid, integer, text) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.worker_release_heartbeat(uuid, uuid, bigint, integer) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.worker_release_is_draining() FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.worker_release_admit_submission() FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_create(uuid, uuid, integer) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_claim(uuid, integer) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_begin_send(uuid, uuid, bigint) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_record_delivered(uuid, uuid, bigint) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_record_known_failure(uuid, uuid, bigint, text, text, timestamptz) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_record_uncertain(uuid, uuid, bigint, text) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_release_unstarted_claim(uuid, uuid, bigint) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_mark_expired_sends_attention() FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.submission_outbox_publication_counts() FROM PUBLIC, anon, authenticated, service_role;

-- An untrusted role must not receive a private capability indirectly through a
-- membership grant. Runtime logins receive these roles separately during
-- reviewed provisioning; untrusted roles never do.
REVOKE image_to_lego_submission,
       image_to_lego_worker,
       image_to_lego_outbox_dispatcher,
       github_release_gate,
       github_release_coordinator
FROM anon, authenticated, service_role;

DO $$
DECLARE
    capability_role text;
BEGIN
    FOREACH capability_role IN ARRAY ARRAY[
        'image_to_lego_submission',
        'image_to_lego_worker',
        'image_to_lego_outbox_dispatcher',
        'github_release_gate',
        'github_release_coordinator'
    ] LOOP
        IF pg_has_role('anon', capability_role, 'member')
           OR pg_has_role('authenticated', capability_role, 'member')
           OR pg_has_role('service_role', capability_role, 'member') THEN
            RAISE EXCEPTION 'Untrusted role inherits private capability role %', capability_role;
        END IF;
    END LOOP;
END;
$$;

-- Do not alter postgres's global default privileges here: that would affect
-- future postgres-owned functions in every schema, including Supabase-managed
-- schemas. Application SECURITY DEFINER functions must revoke PUBLIC/browser
-- execution and grant only a dedicated capability role in the same migration.
