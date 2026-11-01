-- Lets private workers observe a durable drain request while their queues are idle.
-- This does not expose release details to browser-authenticated database roles.

CREATE OR REPLACE FUNCTION public.worker_release_is_draining()
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_state text;
BEGIN
    SELECT state INTO v_state FROM public.worker_release_state WHERE singleton = true;
    IF NOT FOUND OR v_state IS NULL THEN
        RAISE EXCEPTION 'Worker release state cannot be proven';
    END IF;
    RETURN v_state <> 'open';
END;
$$;

REVOKE ALL ON FUNCTION public.worker_release_is_draining() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.worker_release_is_draining() TO image_to_lego_worker;

COMMENT ON FUNCTION public.worker_release_is_draining() IS
    'Returns whether an idle private worker must drain; failures must not be treated as drained.';
