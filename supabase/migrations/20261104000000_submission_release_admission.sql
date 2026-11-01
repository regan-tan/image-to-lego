-- Serializes API admission with release draining. The caller holds this lock
-- until its short job-creation transaction commits or rolls back.
CREATE OR REPLACE FUNCTION public.worker_release_admit_submission()
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE v_state text;
BEGIN
  SELECT state INTO v_state FROM public.worker_release_state WHERE singleton = true FOR UPDATE;
  IF NOT FOUND OR v_state IS NULL THEN RAISE EXCEPTION 'Worker release state cannot be proven'; END IF;
  RETURN v_state = 'open';
END;
$$;
REVOKE ALL ON FUNCTION public.worker_release_admit_submission() FROM PUBLIC;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'image_to_lego_submission') THEN
        CREATE ROLE image_to_lego_submission NOLOGIN NOINHERIT;
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA public TO image_to_lego_submission;
GRANT EXECUTE ON FUNCTION public.worker_release_admit_submission() TO image_to_lego_submission;

COMMENT ON FUNCTION public.worker_release_admit_submission() IS
    'Private API admission gate; grant image_to_lego_submission to the reviewed API login before activation.';
