-- Server-authoritative credits for paid and CPU-intensive job submissions.
-- Accounts are initialized lazily under a row lock, which grants starter credits
-- exactly once without requiring an auth.users trigger.

CREATE TABLE public.credit_accounts (
    owner_id uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    balance integer NOT NULL CHECK (balance >= 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE public.credit_policy (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    starter_credits integer NOT NULL CHECK (starter_credits = 10),
    reconstruction_cost integer NOT NULL CHECK (reconstruction_cost = 2),
    conversion_cost integer NOT NULL CHECK (conversion_cost = 1),
    concurrent_job_limit integer NOT NULL CHECK (concurrent_job_limit = 2),
    reconstruction_window_limit integer NOT NULL CHECK (reconstruction_window_limit = 10),
    conversion_window_limit integer NOT NULL CHECK (conversion_window_limit = 30),
    window_hours integer NOT NULL CHECK (window_hours = 24)
);

INSERT INTO public.credit_policy (
    singleton, starter_credits, reconstruction_cost, conversion_cost,
    concurrent_job_limit, reconstruction_window_limit, conversion_window_limit, window_hours
) VALUES (true, 10, 2, 1, 2, 10, 30, 24);

CREATE TABLE public.credit_transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    job_id uuid,
    project_id uuid,
    job_type text CHECK (job_type IN ('reconstruction', 'conversion')),
    kind text NOT NULL CHECK (kind IN ('starter_grant', 'job_charge', 'job_refund', 'admin_grant')),
    amount integer NOT NULL CHECK (amount <> 0),
    balance_after integer NOT NULL CHECK (balance_after >= 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (
        (kind IN ('starter_grant', 'admin_grant', 'job_refund') AND amount > 0)
        OR (kind = 'job_charge' AND amount < 0)
    ),
    CHECK (
        (kind IN ('job_charge', 'job_refund') AND job_id IS NOT NULL
         AND project_id IS NOT NULL AND job_type IS NOT NULL)
        OR (kind IN ('starter_grant', 'admin_grant') AND job_id IS NULL
            AND project_id IS NULL AND job_type IS NULL)
    )
);

CREATE UNIQUE INDEX credit_transactions_one_starter_per_owner_idx
    ON public.credit_transactions (owner_id) WHERE kind = 'starter_grant';
CREATE UNIQUE INDEX credit_transactions_one_charge_per_job_idx
    ON public.credit_transactions (job_id) WHERE kind = 'job_charge';
CREATE UNIQUE INDEX credit_transactions_one_refund_per_job_idx
    ON public.credit_transactions (job_id) WHERE kind = 'job_refund';
CREATE INDEX credit_transactions_owner_created_at_idx
    ON public.credit_transactions (owner_id, created_at DESC, id DESC);
CREATE INDEX jobs_owner_type_created_at_idx
    ON public.jobs (project_id, type, created_at DESC);

ALTER TABLE public.credit_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.credit_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.credit_transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY credit_accounts_api_owner_read
ON public.credit_accounts FOR SELECT
USING (owner_id = nullif(current_setting('app.current_user_id', true), '')::uuid);
CREATE POLICY credit_policy_api_read
ON public.credit_policy FOR SELECT
USING (true);
CREATE POLICY credit_transactions_api_owner_read
ON public.credit_transactions FOR SELECT
USING (owner_id = nullif(current_setting('app.current_user_id', true), '')::uuid);
CREATE TRIGGER credit_accounts_set_updated_at
BEFORE UPDATE ON public.credit_accounts
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE FUNCTION public.credit_admit_job(p_owner_id uuid, p_job_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_job_type text;
    v_balance integer;
    v_active_count integer;
    v_attempt_count integer;
    v_project_id uuid;
    v_cost integer;
    v_rolling_limit integer;
    v_concurrent_limit integer;
    v_window_hours integer;
BEGIN
    IF p_owner_id IS NULL OR p_job_id IS NULL THEN
        RAISE EXCEPTION 'Credit admission parameters are invalid';
    END IF;
    PERFORM public.credit_ensure_account(p_owner_id);
    SELECT balance INTO v_balance FROM public.credit_accounts WHERE owner_id = p_owner_id FOR UPDATE;

    SELECT j.type, j.project_id INTO v_job_type, v_project_id
    FROM public.jobs j JOIN public.projects p ON p.id = j.project_id
    WHERE j.id = p_job_id AND p.owner_id = p_owner_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Job ownership cannot be proven for credits'; END IF;
    SELECT concurrent_job_limit, window_hours,
           CASE WHEN v_job_type = 'reconstruction' THEN reconstruction_cost ELSE conversion_cost END,
           CASE WHEN v_job_type = 'reconstruction' THEN reconstruction_window_limit ELSE conversion_window_limit END
    INTO v_concurrent_limit, v_window_hours, v_cost, v_rolling_limit
    FROM public.credit_policy WHERE singleton = true;
    IF NOT FOUND THEN RAISE EXCEPTION 'Credit policy cannot be proven'; END IF;

    IF EXISTS (SELECT 1 FROM public.credit_transactions WHERE job_id = p_job_id AND kind = 'job_charge') THEN
        RETURN 'admitted';
    END IF;
    SELECT count(*) INTO v_active_count
    FROM public.jobs j JOIN public.projects p ON p.id = j.project_id
    WHERE p.owner_id = p_owner_id AND j.type = v_job_type AND j.status IN ('queued', 'running');
    IF v_active_count > v_concurrent_limit THEN RETURN 'concurrent_limit'; END IF;
    SELECT count(*) INTO v_attempt_count
    FROM public.credit_transactions
    WHERE owner_id = p_owner_id AND kind = 'job_charge' AND job_type = v_job_type
      AND created_at >= statement_timestamp() - make_interval(hours => v_window_hours);
    IF v_attempt_count >= v_rolling_limit THEN RETURN 'rolling_limit'; END IF;
    IF v_balance < v_cost THEN RETURN 'insufficient_credits'; END IF;

    UPDATE public.credit_accounts SET balance = balance - v_cost WHERE owner_id = p_owner_id
    RETURNING balance INTO v_balance;
    INSERT INTO public.credit_transactions (
        owner_id, job_id, project_id, job_type, kind, amount, balance_after
    ) VALUES (p_owner_id, p_job_id, v_project_id, v_job_type, 'job_charge', -v_cost, v_balance);
    RETURN 'admitted';
END;
$$;

CREATE OR REPLACE FUNCTION public.credit_ensure_account(p_owner_id uuid)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_balance integer; v_starter_credits integer;
BEGIN
    IF p_owner_id IS NULL THEN RAISE EXCEPTION 'Credit account parameters are invalid'; END IF;
    SELECT starter_credits INTO v_starter_credits FROM public.credit_policy WHERE singleton = true;
    IF NOT FOUND THEN RAISE EXCEPTION 'Credit policy cannot be proven'; END IF;
    INSERT INTO public.credit_accounts (owner_id, balance) VALUES (p_owner_id, v_starter_credits)
    ON CONFLICT (owner_id) DO NOTHING;
    SELECT balance INTO v_balance FROM public.credit_accounts WHERE owner_id = p_owner_id FOR UPDATE;
    INSERT INTO public.credit_transactions (owner_id, kind, amount, balance_after)
    SELECT p_owner_id, 'starter_grant', v_starter_credits, v_balance
    WHERE NOT EXISTS (SELECT 1 FROM public.credit_transactions WHERE owner_id = p_owner_id AND kind = 'starter_grant');
    RETURN v_balance;
END;
$$;

CREATE OR REPLACE FUNCTION public.credit_refund_failed_job(p_job_id uuid, p_owner_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_amount integer; v_balance integer; v_project_id uuid; v_job_type text;
BEGIN
    -- Lock the immutable charge row before checking for a prior refund.  The
    -- unique refund index is a backstop, not the duplicate-delivery protocol:
    -- concurrent workers must serialize here and the later caller must return
    -- false instead of updating the balance and raising a uniqueness error.
    SELECT -t.amount, t.project_id, t.job_type INTO v_amount, v_project_id, v_job_type
    FROM public.credit_transactions t
    JOIN public.jobs j ON j.id = t.job_id JOIN public.projects p ON p.id = j.project_id
    WHERE t.job_id = p_job_id AND t.kind = 'job_charge' AND p.owner_id = p_owner_id
      AND j.status IN ('failed', 'canceled')
    FOR UPDATE OF t;
    IF NOT FOUND THEN RETURN false; END IF;
    IF EXISTS (
        SELECT 1 FROM public.credit_transactions
        WHERE job_id = p_job_id AND kind = 'job_refund'
    ) THEN
        RETURN false;
    END IF;
    SELECT balance INTO v_balance FROM public.credit_accounts WHERE owner_id = p_owner_id FOR UPDATE;
    UPDATE public.credit_accounts SET balance = balance + v_amount WHERE owner_id = p_owner_id RETURNING balance INTO v_balance;
    INSERT INTO public.credit_transactions (
        owner_id, job_id, project_id, job_type, kind, amount, balance_after
    ) VALUES (p_owner_id, p_job_id, v_project_id, v_job_type, 'job_refund', v_amount, v_balance);
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.credit_admin_grant(
    p_owner_id uuid,
    p_amount integer
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_balance integer;
BEGIN
    IF p_owner_id IS NULL OR p_amount <= 0 THEN RAISE EXCEPTION 'Credit grant parameters are invalid'; END IF;
    PERFORM public.credit_ensure_account(p_owner_id);
    SELECT balance INTO v_balance FROM public.credit_accounts WHERE owner_id = p_owner_id FOR UPDATE;
    UPDATE public.credit_accounts SET balance = balance + p_amount WHERE owner_id = p_owner_id
    RETURNING balance INTO v_balance;
    INSERT INTO public.credit_transactions (owner_id, kind, amount, balance_after)
    VALUES (p_owner_id, 'admin_grant', p_amount, v_balance);
    RETURN v_balance;
END;
$$;

CREATE OR REPLACE FUNCTION public.credit_reconcile_expired_jobs(p_job_type text)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_job record; v_count integer := 0;
BEGIN
    IF p_job_type NOT IN ('reconstruction', 'conversion') THEN
        RAISE EXCEPTION 'Credit reconciliation job type is invalid';
    END IF;
    FOR v_job IN
        UPDATE public.jobs AS j
        SET status = 'failed', error_code = 'worker_lease_expired',
            error_message = 'The worker did not complete before its lease expired.',
            worker_attempt_id = NULL, worker_lease_expires_at = NULL
        FROM public.projects AS p
        WHERE j.project_id = p.id AND j.type = p_job_type
          AND j.status IN ('queued', 'running')
          AND j.worker_attempt_id IS NOT NULL
          AND j.worker_lease_expires_at <= statement_timestamp()
        RETURNING j.id, p.owner_id
    LOOP
        PERFORM public.credit_refund_failed_job(v_job.id, v_job.owner_id);
        v_count := v_count + 1;
    END LOOP;
    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.credit_fail_dead_lettered_job(
    p_job_id uuid,
    p_owner_id uuid,
    p_job_type text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    UPDATE public.jobs AS j
    SET status = 'failed', error_code = 'queue_delivery_exhausted',
        error_message = 'The worker message exceeded the delivery retry limit.',
        worker_attempt_id = NULL, worker_lease_expires_at = NULL
    FROM public.projects AS p
    WHERE j.id = p_job_id AND j.project_id = p.id AND p.owner_id = p_owner_id
      AND j.type = p_job_type AND j.status IN ('queued', 'running')
      AND (j.worker_attempt_id IS NULL OR j.worker_lease_expires_at <= statement_timestamp());
    IF NOT FOUND THEN RETURN false; END IF;
    PERFORM public.credit_refund_failed_job(p_job_id, p_owner_id);
    RETURN true;
END;
$$;

REVOKE ALL ON TABLE public.credit_accounts, public.credit_policy, public.credit_transactions
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.credit_admit_job(uuid, uuid)
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.credit_ensure_account(uuid)
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.credit_refund_failed_job(uuid, uuid)
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.credit_admin_grant(uuid, integer)
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.credit_reconcile_expired_jobs(text)
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.credit_fail_dead_lettered_job(uuid, uuid, text)
FROM PUBLIC, anon, authenticated, service_role;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'image_to_lego_credits_api') THEN
        CREATE ROLE image_to_lego_credits_api NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'image_to_lego_credits_worker') THEN
        CREATE ROLE image_to_lego_credits_worker NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'image_to_lego_credits_admin') THEN
        CREATE ROLE image_to_lego_credits_admin NOLOGIN NOINHERIT;
    END IF;
END;
$$;
GRANT USAGE ON SCHEMA public TO image_to_lego_credits_api, image_to_lego_credits_worker, image_to_lego_credits_admin;
GRANT SELECT ON TABLE public.credit_accounts, public.credit_policy, public.credit_transactions TO image_to_lego_credits_api;
GRANT EXECUTE ON FUNCTION public.credit_admit_job(uuid, uuid) TO image_to_lego_credits_api;
GRANT EXECUTE ON FUNCTION public.credit_ensure_account(uuid) TO image_to_lego_credits_api;
GRANT EXECUTE ON FUNCTION public.credit_refund_failed_job(uuid, uuid) TO image_to_lego_credits_worker;
GRANT EXECUTE ON FUNCTION public.credit_reconcile_expired_jobs(text) TO image_to_lego_credits_worker;
GRANT EXECUTE ON FUNCTION public.credit_fail_dead_lettered_job(uuid, uuid, text) TO image_to_lego_credits_worker;
GRANT EXECUTE ON FUNCTION public.credit_admin_grant(uuid, integer) TO image_to_lego_credits_admin;
COMMENT ON TABLE public.credit_accounts IS 'Private server-authoritative credit balances; browser roles have no policies.';
COMMENT ON TABLE public.credit_transactions IS 'Immutable audit ledger for credits, charges, and idempotent refunds.';
