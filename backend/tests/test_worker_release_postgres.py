"""PostgreSQL integration tests for the durable worker-release migration."""

import asyncio
import os
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

asyncpg = pytest.importorskip("asyncpg")
pytestmark = pytest.mark.postgres_integration

MIGRATIONS = (
    "20261029000000_worker_job_leases.sql",
    "20261101000000_worker_release_gate.sql",
    "20261102000000_durable_worker_release_coordination.sql",
    "20261103000000_worker_release_drain_status.sql",
    "20261104000000_submission_release_admission.sql",
    "20261105000000_submission_outbox.sql",
    "20261122000000_security_definer_function_permissions.sql",
    "20261123000000_credits.sql",
)
TEST_DATABASE_NAME = "image_to_lego_test"
LOCAL_TEST_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

INTERNAL_SECURITY_DEFINER_FUNCTIONS = (
    "public.worker_release_active_attempt_count()",
    "public.worker_release_try_acquire_attempt(uuid,uuid,text,uuid,integer)",
    "public.worker_release_begin(uuid,uuid,integer)",
    "public.worker_release_transition(uuid,uuid,bigint,text,text)",
    "public.worker_release_recover(uuid,integer,text)",
    "public.worker_release_heartbeat(uuid,uuid,bigint,integer)",
    "public.worker_release_is_draining()",
    "public.worker_release_admit_submission()",
    "public.submission_outbox_create(uuid,uuid,integer)",
    "public.submission_outbox_claim(uuid,integer)",
    "public.submission_outbox_begin_send(uuid,uuid,bigint)",
    "public.submission_outbox_record_delivered(uuid,uuid,bigint)",
    "public.submission_outbox_record_known_failure(uuid,uuid,bigint,text,text,timestamptz)",
    "public.submission_outbox_record_uncertain(uuid,uuid,bigint,text)",
    "public.submission_outbox_release_unstarted_claim(uuid,uuid,bigint)",
    "public.submission_outbox_mark_expired_sends_attention()",
    "public.submission_outbox_publication_counts()",
)

PRIVATE_CAPABILITY_ROLES = (
    "image_to_lego_submission",
    "image_to_lego_worker",
    "image_to_lego_outbox_dispatcher",
    "github_release_gate",
    "github_release_coordinator",
)


def _read_migration_sql(path: Path) -> str:
    """Read committed SQL whether or not an editor wrote a UTF-8 BOM."""
    return path.read_text(encoding="utf-8-sig")


def _require_disposable_database_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    database_name = parsed.path.removeprefix("/")
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname not in LOCAL_TEST_HOSTS
        or database_name != TEST_DATABASE_NAME
    ):
        raise RuntimeError(
            "TEST_DATABASE_URL must name the local disposable image_to_lego_test database."
        )


@pytest.fixture(scope="session")
async def postgres_database() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        if os.environ.get("REQUIRE_POSTGRES_INTEGRATION") == "true":
            raise RuntimeError("TEST_DATABASE_URL is required for PostgreSQL integration tests.")
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests.")
    _require_disposable_database_url(database_url)
    connection = await asyncpg.connect(database_url)
    with suppress(asyncpg.exceptions.DuplicateObjectError):
        await connection.execute("create role authenticated nologin")
    with suppress(asyncpg.exceptions.DuplicateObjectError):
        await connection.execute("create role anon nologin")
    with suppress(asyncpg.exceptions.DuplicateObjectError):
        await connection.execute("create role service_role nologin")
    await connection.execute(
        """
        drop schema public cascade;
        create schema public;
        create schema if not exists auth;
        create table if not exists auth.users (id uuid primary key);
        create extension if not exists pgcrypto;
        create table public.projects (id uuid primary key, owner_id uuid not null);
        create table public.jobs (
            id uuid primary key,
            project_id uuid not null references public.projects(id) on delete cascade,
            type text not null,
            status text not null,
            idempotency_key text,
            provider_job_id text,
            error_code text,
            error_message text,
            created_at timestamptz not null default statement_timestamp(),
            updated_at timestamptz not null default statement_timestamp(),
            unique (project_id, type, idempotency_key)
        );
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
        """
    )
    migration_directory = Path(__file__).parents[2] / "supabase" / "migrations"
    for migration in MIGRATIONS:
        if migration == "20261122000000_security_definer_function_permissions.sql":
            # Reproduce the audited production exposure before applying the
            # remediation, including a direct service_role grant.
            for function_signature in INTERNAL_SECURITY_DEFINER_FUNCTIONS:
                await connection.execute(
                    f"grant execute on function {function_signature} "
                    "to anon, authenticated, service_role"
                )
        await connection.execute(_read_migration_sql(migration_directory / migration))
    await connection.execute(
        """
        drop role if exists credit_test_api_login;
        drop role if exists credit_test_worker_login;
        create role credit_test_api_login login inherit password 'local-credit-test-password';
        create role credit_test_worker_login login inherit password 'local-credit-test-password';
        grant image_to_lego_credits_api to credit_test_api_login;
        grant image_to_lego_credits_worker to credit_test_worker_login;
        """
    )
    yield database_url
    await connection.close()


@pytest.fixture
async def database(postgres_database: str) -> str:
    connection = await asyncpg.connect(postgres_database)
    await connection.execute(
        """
        truncate public.credit_transactions, public.credit_accounts,
                 public.submission_outbox, public.jobs, public.projects,
                 public.worker_release_audit;
        insert into public.worker_release_state (singleton, state)
        values (true, 'open')
        on conflict (singleton) do nothing;
        update public.worker_release_state
        set state = 'open', release_id = null, controller_id = null,
            controller_heartbeat_expires_at = null;
        """
    )
    await connection.close()
    return postgres_database


async def _create_credit_job(database_url: str, job_type: str) -> tuple[UUID, UUID, UUID]:
    owner_id, project_id, job_id = uuid4(), uuid4(), uuid4()
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute("insert into auth.users (id) values ($1)", owner_id)
        await connection.execute(
            "insert into public.projects (id, owner_id) values ($1, $2)", project_id, owner_id
        )
        await connection.execute(
            """
            insert into public.jobs (id, project_id, type, status, idempotency_key)
            values ($1, $2, $3, 'queued', $4)
            """,
            job_id,
            project_id,
            job_type,
            str(uuid4()),
        )
    finally:
        await connection.close()
    return owner_id, project_id, job_id


@pytest.mark.asyncio
async def test_credit_grant_admission_refund_and_project_deletion_keep_history(
    database: str,
) -> None:
    owner_id, project_id, job_id = await _create_credit_job(database, "reconstruction")
    connection = await asyncpg.connect(database)
    try:
        assert await connection.fetchval("select public.credit_admin_grant($1, 3)", owner_id) == 13
        assert (
            await connection.fetchval("select public.credit_admit_job($1, $2)", owner_id, job_id)
            == "admitted"
        )
        await connection.execute("update public.jobs set status = 'failed' where id = $1", job_id)
        assert await connection.fetchval(
            "select public.credit_refund_failed_job($1, $2)", job_id, owner_id
        ) is True
        await connection.execute("delete from public.projects where id = $1", project_id)
        assert await connection.fetchval(
            "select count(*) from public.credit_transactions where job_id = $1", job_id
        ) == 2
        assert await connection.fetchval(
            "select balance from public.credit_accounts where owner_id = $1", owner_id
        ) == 13
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_credit_policy_prevents_parallel_overcharging(database: str) -> None:
    owner_id, _, first_job = await _create_credit_job(database, "reconstruction")
    _, second_project, second_job = await _create_credit_job(database, "reconstruction")
    connection = await asyncpg.connect(database)
    second_connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "update public.projects set owner_id = $1 where id = $2", owner_id, second_project
        )
        first, second = await asyncio.gather(
            connection.fetchval("select public.credit_admit_job($1, $2)", owner_id, first_job),
            second_connection.fetchval(
                "select public.credit_admit_job($1, $2)", owner_id, second_job
            ),
        )
        assert first == second == "admitted"
        assert await connection.fetchval(
            "select balance from public.credit_accounts where owner_id = $1", owner_id
        ) == 6
    finally:
        await connection.close()
        await second_connection.close()


@pytest.mark.asyncio
async def test_credit_account_grant_is_exactly_once_under_concurrent_access(database: str) -> None:
    owner_id = uuid4()
    setup = await asyncpg.connect(database)
    first = await asyncpg.connect(database)
    second = await asyncpg.connect(database)
    try:
        await setup.execute("insert into auth.users (id) values ($1)", owner_id)
        balances = await asyncio.gather(
            first.fetchval("select public.credit_ensure_account($1)", owner_id),
            second.fetchval("select public.credit_ensure_account($1)", owner_id),
        )
        assert balances == [10, 10]
        assert await setup.fetchval(
            "select count(*) from public.credit_transactions "
            "where owner_id = $1 and kind = 'starter_grant'",
            owner_id,
        ) == 1
    finally:
        await setup.close()
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_credit_admission_charges_each_job_type_once_and_is_idempotent(database: str) -> None:
    owner_id, _, reconstruction_job = await _create_credit_job(database, "reconstruction")
    _, conversion_project, conversion_job = await _create_credit_job(database, "conversion")
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "update public.projects set owner_id = $1 where id = $2", owner_id, conversion_project
        )
        assert await connection.fetchval(
            "select public.credit_admit_job($1, $2)", owner_id, reconstruction_job
        ) == "admitted"
        assert await connection.fetchval(
            "select public.credit_admit_job($1, $2)", owner_id, reconstruction_job
        ) == "admitted"
        assert await connection.fetchval(
            "select public.credit_admit_job($1, $2)", owner_id, conversion_job
        ) == "admitted"
        assert await connection.fetchval(
            "select balance from public.credit_accounts where owner_id = $1", owner_id
        ) == 7
        assert await connection.fetchval(
            "select count(*) from public.credit_transactions "
            "where owner_id = $1 and kind = 'job_charge' and job_type = 'reconstruction'",
            owner_id,
        ) == 1
        assert await connection.fetchval(
            "select count(*) from public.credit_transactions "
            "where owner_id = $1 and kind = 'job_charge' and job_type = 'conversion'",
            owner_id,
        ) == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_credit_charge_rolls_back_with_failed_run_or_outbox_creation(database: str) -> None:
    owner_id, _, job_id = await _create_credit_job(database, "reconstruction")
    connection = await asyncpg.connect(database)
    try:
        transaction = connection.transaction()
        await transaction.start()
        try:
            assert await connection.fetchval(
                "select public.credit_admit_job($1, $2)", owner_id, job_id
            ) == "admitted"
            # The outbox function rejects this invalid schema version.  It
            # stands in for any later run/outbox failure in the repository
            # transaction and must roll back the preceding charge as well.
            await connection.fetchval(
                "select public.submission_outbox_create($1, $2, 0)", job_id, owner_id
            )
        except asyncpg.PostgresError:
            await transaction.rollback()
        else:
            raise AssertionError("invalid outbox creation unexpectedly succeeded")
        assert await connection.fetchval(
            "select count(*) from public.credit_transactions where job_id = $1", job_id
        ) == 0
        assert await connection.fetchval(
            "select count(*) from public.credit_accounts where owner_id = $1", owner_id
        ) == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_credit_refund_is_exactly_once_for_concurrent_duplicate_delivery(
    database: str,
) -> None:
    owner_id, _, job_id = await _create_credit_job(database, "reconstruction")
    setup = await asyncpg.connect(database)
    first = await asyncpg.connect(database)
    second = await asyncpg.connect(database)
    try:
        assert (
            await setup.fetchval("select public.credit_admit_job($1, $2)", owner_id, job_id)
            == "admitted"
        )
        await setup.execute("update public.jobs set status = 'failed' where id = $1", job_id)
        results = await asyncio.gather(
            first.fetchval("select public.credit_refund_failed_job($1, $2)", job_id, owner_id),
            second.fetchval("select public.credit_refund_failed_job($1, $2)", job_id, owner_id),
        )
        assert sorted(results) == [False, True]
        assert await setup.fetchval(
            "select count(*) from public.credit_transactions "
            "where job_id = $1 and kind = 'job_refund'",
            job_id,
        ) == 1
        assert await setup.fetchval(
            "select balance from public.credit_accounts where owner_id = $1", owner_id
        ) == 10
    finally:
        await setup.close()
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_credit_reconciles_expired_leases_and_dead_letters_once(database: str) -> None:
    owner_id, _, expired_job = await _create_credit_job(database, "reconstruction")
    _, conversion_project, dead_letter_job = await _create_credit_job(database, "conversion")
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "update public.projects set owner_id = $1 where id = $2", owner_id, conversion_project
        )
        for job_id in (expired_job, dead_letter_job):
            assert await connection.fetchval(
                "select public.credit_admit_job($1, $2)", owner_id, job_id
            ) == "admitted"
        await connection.execute(
            "update public.jobs set worker_attempt_id = $2, "
            "worker_lease_expires_at = now() - interval '1 second' where id = $1",
            expired_job,
            uuid4(),
        )
        assert await connection.fetchval(
            "select public.credit_reconcile_expired_jobs('reconstruction')"
        ) == 1
        assert await connection.fetchval(
            "select public.credit_fail_dead_lettered_job($1, $2, 'conversion')",
            dead_letter_job,
            owner_id,
        ) is True
        assert await connection.fetchval(
            "select public.credit_fail_dead_lettered_job($1, $2, 'conversion')",
            dead_letter_job,
            owner_id,
        ) is False
        assert await connection.fetchval(
            "select count(*) from public.credit_transactions "
            "where owner_id = $1 and kind = 'job_refund'",
            owner_id,
        ) == 2
        assert await connection.fetchval(
            "select balance from public.credit_accounts where owner_id = $1", owner_id
        ) == 10
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_credit_policy_allows_at_most_two_active_jobs_per_type(database: str) -> None:
    owner_id, _, first_job = await _create_credit_job(database, "reconstruction")
    _, second_project, second_job = await _create_credit_job(database, "reconstruction")
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "update public.projects set owner_id = $1 where id = $2",
            owner_id,
            second_project,
        )
        assert (
            await connection.fetchval("select public.credit_admit_job($1, $2)", owner_id, first_job)
            == "admitted"
        )
        assert (
            await connection.fetchval(
                "select public.credit_admit_job($1, $2)", owner_id, second_job
            )
            == "admitted"
        )
        _, third_project, third_job = await _create_credit_job(database, "reconstruction")
        await connection.execute(
            "update public.projects set owner_id = $1 where id = $2", owner_id, third_project
        )
        assert (
            await connection.fetchval("select public.credit_admit_job($1, $2)", owner_id, third_job)
            == "concurrent_limit"
        )
        assert await connection.fetchval(
            "select count(*) from public.credit_transactions "
            "where owner_id = $1 and kind = 'job_charge'", owner_id
        ) == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_restricted_credit_roles_and_browser_access_boundaries(database: str) -> None:
    owner_id, _, job_id = await _create_credit_job(database, "reconstruction")
    other_owner_id = uuid4()
    admin = await asyncpg.connect(database)
    api = await asyncpg.connect(
        database, user="credit_test_api_login", password="local-credit-test-password"
    )
    worker = await asyncpg.connect(
        database, user="credit_test_worker_login", password="local-credit-test-password"
    )
    browser = await asyncpg.connect(database)
    try:
        await admin.execute("insert into auth.users (id) values ($1)", other_owner_id)
        assert await api.fetchval("select public.credit_ensure_account($1)", owner_id) == 10
        assert await api.fetchval("select public.credit_ensure_account($1)", other_owner_id) == 10
        assert (
            await api.fetchval("select public.credit_admit_job($1, $2)", owner_id, job_id)
            == "admitted"
        )
        await api.execute("select set_config('app.current_user_id', $1, false)", str(owner_id))
        assert await api.fetchval("select balance from public.credit_accounts") == 8
        assert await api.fetchval("select count(*) from public.credit_accounts") == 1
        await api.execute(
            "select set_config('app.current_user_id', $1, false)", str(other_owner_id)
        )
        assert await api.fetchval("select balance from public.credit_accounts") == 10
        assert await api.fetchval("select count(*) from public.credit_accounts") == 1
        await admin.execute("update public.jobs set status = 'failed' where id = $1", job_id)
        assert await worker.fetchval(
            "select public.credit_refund_failed_job($1, $2)", job_id, owner_id
        ) is True
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await worker.fetchval("select balance from public.credit_accounts")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await worker.fetchval("select public.credit_admit_job($1, $2)", owner_id, job_id)
        await browser.execute("set role authenticated")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await browser.fetchval("select balance from public.credit_accounts")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await browser.fetchval("select public.credit_ensure_account($1)", owner_id)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await browser.fetchval(
                "select public.credit_refund_failed_job($1, $2)", job_id, owner_id
            )
    finally:
        await admin.close()
        await api.close()
        await worker.close()
        await browser.close()


async def _create_job(database_url: str, job_type: str = "reconstruction") -> tuple[UUID, UUID]:
    job_id, project_id, owner_id = uuid4(), uuid4(), uuid4()
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(
            "insert into public.projects (id, owner_id) values ($1, $2)", project_id, owner_id
        )
        await connection.execute(
            "insert into public.jobs (id, project_id, type, status) values ($1, $2, $3, 'queued')",
            job_id,
            project_id,
            job_type,
        )
        return job_id, owner_id
    finally:
        await connection.close()


async def _acquire(connection: object, job_id: UUID, owner_id: UUID, job_type: str) -> str:
    return await _acquire_with_lease(connection, job_id, owner_id, job_type, 60)


async def _acquire_with_lease(
    connection: object, job_id: UUID, owner_id: UUID, job_type: str, lease_seconds: int
) -> str:
    row = await connection.fetchrow(
        "select status from public.worker_release_try_acquire_attempt($1, $2, $3, $4, $5)",
        job_id,
        owner_id,
        job_type,
        uuid4(),
        lease_seconds,
    )
    assert row is not None
    return str(row["status"])


async def _begin(connection: object, release_id: UUID, controller_id: UUID) -> int:
    return int(
        await connection.fetchval(
            "select public.worker_release_begin($1, $2, 60)", release_id, controller_id
        )
    )


async def _admit(connection: object) -> bool:
    return bool(await connection.fetchval("select public.worker_release_admit_submission()"))


async def _transition_to_quiescent(
    connection: object, release_id: UUID, controller_id: UUID, token: int
) -> None:
    await connection.execute(
        "select public.worker_release_transition($1, $2, $3, 'quiescent')",
        release_id,
        controller_id,
        token,
    )


async def _heartbeat(connection: object, release_id: UUID, controller_id: UUID, token: int) -> None:
    await connection.execute(
        "select public.worker_release_heartbeat($1, $2, $3, 60)",
        release_id,
        controller_id,
        token,
    )


async def _expire_controller_heartbeat(connection: object) -> None:
    await connection.execute(
        """
        update public.worker_release_state
        set controller_heartbeat_expires_at = now() - interval '1 second'
        """
    )


async def _release_state(connection: object) -> str:
    return str(await connection.fetchval("select state from public.worker_release_state"))


async def _create_outbox(connection: object, job_id: UUID, owner_id: UUID) -> UUID:
    return await connection.fetchval(
        "select public.submission_outbox_create($1, $2, 1)", job_id, owner_id
    )


async def _claim_outbox(connection: object, dispatcher_id: UUID) -> object:
    return await connection.fetchrow(
        "select * from public.submission_outbox_claim($1, 60)", dispatcher_id
    )


def test_read_migration_sql_accepts_utf8_with_and_without_bom() -> None:
    migration_directory = Path(__file__).parents[2] / "supabase" / "migrations"
    bom_prefixed = migration_directory / "20261029000000_worker_job_leases.sql"
    normal = migration_directory / "20261102000000_durable_worker_release_coordination.sql"

    assert _read_migration_sql(bom_prefixed).startswith("-- Worker lease tracking")
    assert _read_migration_sql(normal).startswith("-- Durable worker release coordination")


def test_security_definer_permission_migration_precedes_credits() -> None:
    assert MIGRATIONS.index("20261122000000_security_definer_function_permissions.sql") == (
        MIGRATIONS.index("20261123000000_credits.sql") - 1
    )


def test_security_definer_permission_migration_revokes_every_audited_signature() -> None:
    migration_directory = Path(__file__).parents[2] / "supabase" / "migrations"
    content = _read_migration_sql(
        migration_directory / "20261122000000_security_definer_function_permissions.sql"
    )
    compact_content = "".join(content.split())
    for function_signature in INTERNAL_SECURITY_DEFINER_FUNCTIONS:
        expected_revoke = (
            f"REVOKE EXECUTE ON FUNCTION {function_signature} "
            "FROM PUBLIC, anon, authenticated, service_role;"
        )
        assert "".join(expected_revoke.split()) in compact_content

    assert "ALTER DEFAULT PRIVILEGES" not in content
    assert (
        "REVOKEimage_to_lego_submission,image_to_lego_worker,"
        "image_to_lego_outbox_dispatcher,github_release_gate,github_release_coordinator"
        "FROManon,authenticated,service_role;"
    ) in compact_content


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://postgres:postgres@db.example.com/image_to_lego_test",
        "postgresql://postgres:postgres@localhost/postgres",
        "https://localhost/image_to_lego_test",
    ],
)
def test_disposable_database_guard_rejects_non_test_targets(database_url: str) -> None:
    with pytest.raises(RuntimeError, match="local disposable"):
        _require_disposable_database_url(database_url)


@pytest.mark.asyncio
async def test_missing_release_singleton_cannot_admit_worker_attempt(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        await connection.execute("delete from public.worker_release_state where singleton = true")
        with pytest.raises(asyncpg.PostgresError, match="cannot be proven"):
            await _acquire(connection, job_id, owner_id, "reconstruction")
        assert await connection.fetchval(
            "select worker_attempt_id is null from public.jobs where id = $1", job_id
        )
    finally:
        await connection.execute(
            "insert into public.worker_release_state (singleton, state) values (true, 'open')"
        )
        await connection.close()


@pytest.mark.asyncio
async def test_open_gate_admits_submission(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        assert await _admit(connection) is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_draining_gate_rejects_submission(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        await _begin(connection, uuid4(), uuid4())
        assert await _admit(connection) is False
        assert await _release_state(connection) == "draining"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_admission_lock_serializes_with_draining(database: str) -> None:
    admission, controller = await asyncpg.connect(database), await asyncpg.connect(database)
    try:
        transaction = admission.transaction()
        await transaction.start()
        assert await _admit(admission) is True
        release_task = asyncio.create_task(_begin(controller, uuid4(), uuid4()))
        await asyncio.wait_for(asyncio.sleep(0), timeout=1)
        assert not release_task.done()
        await transaction.commit()
        await asyncio.wait_for(release_task, timeout=1)
        assert await _admit(admission) is False
    finally:
        await admission.close()
        await controller.close()


@pytest.mark.asyncio
async def test_missing_release_singleton_fails_closed_for_submission(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        await connection.execute("delete from public.worker_release_state where singleton = true")
        with pytest.raises(asyncpg.PostgresError, match="cannot be proven"):
            await _admit(connection)
    finally:
        await connection.execute(
            "insert into public.worker_release_state (singleton, state) values (true, 'open')"
        )
        await connection.close()


@pytest.mark.asyncio
async def test_idle_worker_drain_status_is_durable_and_fails_closed(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        assert await connection.fetchval("select public.worker_release_is_draining()") is False
        await _begin(connection, uuid4(), uuid4())
        assert await connection.fetchval("select public.worker_release_is_draining()") is True
        await connection.execute("delete from public.worker_release_state where singleton = true")
        with pytest.raises(asyncpg.PostgresError):
            await connection.fetchval("select public.worker_release_is_draining()")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_committed_lease_is_visible_before_draining(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    worker, controller = await asyncpg.connect(database), await asyncpg.connect(database)
    try:
        assert await _acquire(worker, job_id, owner_id, "reconstruction") == "acquired"
        await _begin(controller, uuid4(), uuid4())
        assert await worker.fetchval(
            "select worker_attempt_id is not null from public.jobs where id = $1", job_id
        )
    finally:
        await worker.close()
        await controller.close()


@pytest.mark.asyncio
async def test_draining_committed_first_blocks_new_lease(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    controller, worker = await asyncpg.connect(database), await asyncpg.connect(database)
    try:
        await _begin(controller, uuid4(), uuid4())
        assert await _acquire(worker, job_id, owner_id, "reconstruction") == "release_blocked"
    finally:
        await controller.close()
        await worker.close()


@pytest.mark.asyncio
async def test_overlapping_claim_and_release_have_one_serialized_winner(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    worker, controller = await asyncpg.connect(database), await asyncpg.connect(database)
    release_started = asyncio.Event()

    async def begin_release() -> int:
        release_started.set()
        return await _begin(controller, uuid4(), uuid4())

    try:
        transaction = worker.transaction()
        await transaction.start()
        assert await _acquire(worker, job_id, owner_id, "reconstruction") == "acquired"
        release_task = asyncio.create_task(begin_release())
        await release_started.wait()
        await transaction.commit()
        assert await release_task > 0
        assert await worker.fetchval(
            "select worker_attempt_id is not null from public.jobs where id = $1", job_id
        )
    finally:
        await worker.close()
        await controller.close()


@pytest.mark.asyncio
async def test_only_one_controller_can_own_a_release(database: str) -> None:
    first, second = await asyncpg.connect(database), await asyncpg.connect(database)
    try:
        results = await asyncio.gather(
            _begin(first, uuid4(), uuid4()),
            _begin(second, uuid4(), uuid4()),
            return_exceptions=True,
        )
        assert sum(isinstance(result, int) for result in results) == 1
        assert sum(isinstance(result, Exception) for result in results) == 1
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_stale_controller_cannot_transition_or_reopen_gate(database: str) -> None:
    release_id, controller_id = uuid4(), uuid4()
    connection = await asyncpg.connect(database)
    try:
        token = await _begin(connection, release_id, controller_id)
        await _expire_controller_heartbeat(connection)
        replacement_token = await connection.fetchval(
            "select public.worker_release_recover($1, 60, 'test recovery')", uuid4()
        )
        with pytest.raises(asyncpg.PostgresError):
            await connection.execute(
                "select public.worker_release_transition($1, $2, $3, 'open')",
                release_id,
                controller_id,
                token,
            )
        assert replacement_token > token
        assert await _release_state(connection) == "blocked"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_crashed_controller_does_not_reopen_the_gate(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        await _begin(connection, uuid4(), uuid4())
        await _expire_controller_heartbeat(connection)
        with pytest.raises(asyncpg.PostgresError):
            await _begin(connection, uuid4(), uuid4())
        assert await _release_state(connection) == "draining"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_expired_controller_cannot_transition_or_renew_without_recovery(
    database: str,
) -> None:
    release_id, controller_id = uuid4(), uuid4()
    connection = await asyncpg.connect(database)
    try:
        token = await _begin(connection, release_id, controller_id)
        await _expire_controller_heartbeat(connection)
        with pytest.raises(asyncpg.PostgresError, match="heartbeat expired"):
            await connection.execute(
                "select public.worker_release_transition($1, $2, $3, 'blocked')",
                release_id,
                controller_id,
                token,
            )
        with pytest.raises(asyncpg.PostgresError, match="Stale or unauthorized"):
            await _heartbeat(connection, release_id, controller_id, token)
        recovered_token = await connection.fetchval(
            "select public.worker_release_recover($1, 60, 'expired controller')", uuid4()
        )
        assert recovered_token > token
        with pytest.raises(asyncpg.PostgresError, match="Stale or unauthorized"):
            await _transition_to_quiescent(connection, release_id, controller_id, token)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_recovery_fences_concurrent_stale_controller_operation(database: str) -> None:
    release_id, controller_id = uuid4(), uuid4()
    controller = await asyncpg.connect(database)
    recovery = await asyncpg.connect(database)
    try:
        token = await _begin(controller, release_id, controller_id)
        await _expire_controller_heartbeat(controller)
        results = await asyncio.gather(
            recovery.fetchval(
                "select public.worker_release_recover($1, 60, 'concurrent recovery')", uuid4()
            ),
            _heartbeat(controller, release_id, controller_id, token),
            return_exceptions=True,
        )
        assert isinstance(results[0], int)
        assert results[0] > token
        assert isinstance(results[1], asyncpg.PostgresError)
        assert await _release_state(recovery) == "blocked"
    finally:
        await controller.close()
        await recovery.close()


@pytest.mark.asyncio
async def test_invalid_function_arguments_are_rejected(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        for job_type, lease_seconds in (
            ("invalid", 60),
            ("reconstruction", 0),
            ("conversion", 601),
        ):
            with pytest.raises(asyncpg.PostgresError, match="parameters are invalid"):
                await _acquire_with_lease(connection, job_id, owner_id, job_type, lease_seconds)
        with pytest.raises(asyncpg.PostgresError, match="parameters are invalid"):
            await connection.fetchval(
                "select public.worker_release_begin($1, $2, $3)", uuid4(), uuid4(), 3601
            )
        with pytest.raises(asyncpg.PostgresError, match="parameters are invalid"):
            await connection.fetchval(
                "select public.worker_release_begin($1, $2, 60)", None, uuid4()
            )
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", ["reconstruction", "conversion"])
async def test_both_worker_paths_cannot_bypass_the_release_gate(
    database: str, job_type: str
) -> None:
    job_id, owner_id = await _create_job(database, job_type)
    connection = await asyncpg.connect(database)
    try:
        await _begin(connection, uuid4(), uuid4())
        assert await _acquire(connection, job_id, owner_id, job_type) == "release_blocked"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_unproven_database_state_blocks_quiescence(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        await _acquire(connection, job_id, owner_id, "reconstruction")
        await connection.execute(
            """
            update public.jobs
            set worker_lease_expires_at = now() - interval '1 second'
            where id = $1
            """,
            job_id,
        )
        release_id, controller_id = uuid4(), uuid4()
        token = await _begin(connection, release_id, controller_id)
        with pytest.raises(asyncpg.PostgresError):
            await _transition_to_quiescent(connection, release_id, controller_id, token)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_active_lease_prevents_quiescent_transition(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        await _acquire(connection, job_id, owner_id, "reconstruction")
        release_id, controller_id = uuid4(), uuid4()
        token = await _begin(connection, release_id, controller_id)
        with pytest.raises(asyncpg.PostgresError):
            await _transition_to_quiescent(connection, release_id, controller_id, token)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_privileges_prevent_unauthorized_release_state_changes(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        await connection.execute("set role authenticated")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute("update public.worker_release_state set state = 'open'")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute(
                "select public.worker_release_begin($1, $2, 60)", uuid4(), uuid4()
            )
        await connection.execute("reset role")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_outbox_claim_and_delivery_are_fenced(database: str) -> None:
    job_id, owner_id = await _create_job(database, "reconstruction")
    connection = await asyncpg.connect(database)
    try:
        outbox_id = await _create_outbox(connection, job_id, owner_id)
        dispatcher_id = uuid4()
        claim = await _claim_outbox(connection, dispatcher_id)
        assert claim is not None
        assert claim["status"] == "claimed"
        assert claim["outbox_id"] == outbox_id
        assert claim["message_type"] == "reconstruction_job"
        assert claim["owner_id"] == owner_id
        assert (await _claim_outbox(connection, uuid4()))["status"] == "empty"

        token = int(claim["dispatch_fencing_token"])
        assert await connection.fetchval(
            "select public.submission_outbox_begin_send($1, $2, $3)",
            outbox_id,
            dispatcher_id,
            token,
        )
        assert not await connection.fetchval(
            "select public.submission_outbox_record_delivered($1, $2, $3)",
            outbox_id,
            uuid4(),
            token,
        )
        assert await connection.fetchval(
            "select public.submission_outbox_record_delivered($1, $2, $3)",
            outbox_id,
            dispatcher_id,
            token,
        )
        assert await connection.fetchval(
            "select status = 'delivered' from public.submission_outbox where id = $1", outbox_id
        )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_draining_rejects_outbox_send_and_pending_work_can_resume(database: str) -> None:
    job_id, owner_id = await _create_job(database, "conversion")
    connection = await asyncpg.connect(database)
    try:
        outbox_id = await _create_outbox(connection, job_id, owner_id)
        dispatcher_id = uuid4()
        claim = await _claim_outbox(connection, dispatcher_id)
        assert claim is not None
        token = int(claim["dispatch_fencing_token"])

        release_id, controller_id = uuid4(), uuid4()
        release_token = await _begin(connection, release_id, controller_id)
        assert not await connection.fetchval(
            "select public.submission_outbox_begin_send($1, $2, $3)",
            outbox_id,
            dispatcher_id,
            token,
        )
        assert await connection.fetchval(
            "select public.submission_outbox_release_unstarted_claim($1, $2, $3)",
            outbox_id,
            dispatcher_id,
            token,
        )
        assert await connection.fetchval(
            "select status = 'pending' from public.submission_outbox where id = $1", outbox_id
        )
        await _transition_to_quiescent(connection, release_id, controller_id, release_token)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_in_flight_or_uncertain_outbox_publication_blocks_quiescence(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        outbox_id = await _create_outbox(connection, job_id, owner_id)
        dispatcher_id = uuid4()
        claim = await _claim_outbox(connection, dispatcher_id)
        assert claim is not None
        token = int(claim["dispatch_fencing_token"])
        assert await connection.fetchval(
            "select public.submission_outbox_begin_send($1, $2, $3)",
            outbox_id,
            dispatcher_id,
            token,
        )

        release_id, controller_id = uuid4(), uuid4()
        release_token = await _begin(connection, release_id, controller_id)
        with pytest.raises(asyncpg.PostgresError, match="publications are still active"):
            await _transition_to_quiescent(connection, release_id, controller_id, release_token)

        assert await connection.fetchval(
            "select public.submission_outbox_record_uncertain($1, $2, $3, $4)",
            outbox_id,
            dispatcher_id,
            token,
            "test timeout after send started",
        )
        with pytest.raises(asyncpg.PostgresError, match="publications are still active"):
            await _transition_to_quiescent(connection, release_id, controller_id, release_token)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_known_outbox_failure_returns_intent_to_pending(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        outbox_id = await _create_outbox(connection, job_id, owner_id)
        dispatcher_id = uuid4()
        claim = await _claim_outbox(connection, dispatcher_id)
        assert claim is not None
        token = int(claim["dispatch_fencing_token"])
        assert await connection.fetchval(
            "select public.submission_outbox_begin_send($1, $2, $3)",
            outbox_id,
            dispatcher_id,
            token,
        )
        assert await connection.fetchval(
            """
            select public.submission_outbox_record_known_failure(
                $1, $2, $3, $4, $5, statement_timestamp() + interval '1 second'
            )
            """,
            outbox_id,
            dispatcher_id,
            token,
            "service_bus_unavailable",
            "Service Bus rejected the send before accepting it.",
        )
        counts = await connection.fetchrow(
            "select * from public.submission_outbox_publication_counts()"
        )
        assert counts is not None
        assert counts["pending_count"] == 1
        assert counts["in_flight_count"] == 0
        assert counts["attention_required_count"] == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_authenticated_role_cannot_read_or_dispatch_outbox(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        await connection.execute("set role authenticated")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetch("select * from public.submission_outbox")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _claim_outbox(connection, uuid4())
        await connection.execute("reset role")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_untrusted_roles_cannot_execute_internal_security_definer_functions(
    database: str,
) -> None:
    connection = await asyncpg.connect(database)
    try:
        for browser_role in ("anon", "authenticated", "service_role"):
            for function_signature in INTERNAL_SECURITY_DEFINER_FUNCTIONS:
                assert not await connection.fetchval(
                    "select has_function_privilege($1, $2::regprocedure, 'execute')",
                    browser_role,
                    function_signature,
                )

        await connection.execute("set role authenticated")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetchval("select public.worker_release_admit_submission()")
        await connection.execute("reset role")
        await connection.execute("set role service_role")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetchval("select public.worker_release_admit_submission()")
        await connection.execute("reset role")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_untrusted_roles_do_not_inherit_private_capability_roles(database: str) -> None:
    connection = await asyncpg.connect(database)
    try:
        for browser_role in ("anon", "authenticated", "service_role"):
            for capability_role in PRIVATE_CAPABILITY_ROLES:
                assert not await connection.fetchval(
                    "select pg_has_role($1, $2, 'member')",
                    browser_role,
                    capability_role,
                )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_private_capability_roles_keep_their_intended_function_access(database: str) -> None:
    expected_grants = {
        "image_to_lego_submission": (
            "public.worker_release_admit_submission()",
            "public.submission_outbox_create(uuid,uuid,integer)",
        ),
        "image_to_lego_worker": (
            "public.worker_release_try_acquire_attempt(uuid,uuid,text,uuid,integer)",
            "public.worker_release_is_draining()",
        ),
        "image_to_lego_outbox_dispatcher": (
            "public.submission_outbox_claim(uuid,integer)",
            "public.submission_outbox_begin_send(uuid,uuid,bigint)",
            "public.submission_outbox_record_delivered(uuid,uuid,bigint)",
            "public.submission_outbox_record_known_failure(uuid,uuid,bigint,text,text,timestamptz)",
            "public.submission_outbox_record_uncertain(uuid,uuid,bigint,text)",
            "public.submission_outbox_release_unstarted_claim(uuid,uuid,bigint)",
            "public.submission_outbox_mark_expired_sends_attention()",
            "public.submission_outbox_publication_counts()",
        ),
        "github_release_gate": ("public.worker_release_active_attempt_count()",),
        "github_release_coordinator": (
            "public.worker_release_begin(uuid,uuid,integer)",
            "public.worker_release_transition(uuid,uuid,bigint,text,text)",
            "public.worker_release_recover(uuid,integer,text)",
            "public.worker_release_heartbeat(uuid,uuid,bigint,integer)",
            "public.submission_outbox_publication_counts()",
        ),
    }
    connection = await asyncpg.connect(database)
    try:
        for role, function_signatures in expected_grants.items():
            for function_signature in function_signatures:
                assert await connection.fetchval(
                    "select has_function_privilege($1, $2::regprocedure, 'execute')",
                    role,
                    function_signature,
                )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_worker_role_can_acquire_an_attempt(database: str) -> None:
    job_id, owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        await connection.execute("set role image_to_lego_worker")
        assert await _acquire(connection, job_id, owner_id, "reconstruction") == "acquired"
        await connection.execute("reset role")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_authenticated_role_cannot_acquire_own_or_another_users_attempt(
    database: str,
) -> None:
    own_job_id, own_owner_id = await _create_job(database)
    other_job_id, other_owner_id = await _create_job(database)
    connection = await asyncpg.connect(database)
    try:
        await connection.execute("set role authenticated")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _acquire(connection, own_job_id, own_owner_id, "reconstruction")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _acquire(connection, other_job_id, other_owner_id, "reconstruction")
        await connection.execute("reset role")
    finally:
        await connection.close()

async def _create_job_with_outbox(
    connection: object,
    *,
    project_id: UUID,
    owner_id: UUID,
    job_type: str,
    idempotency_key: str,
) -> UUID | None:
    async with connection.transaction():
        admitted = await _admit(connection)
        if not admitted:
            return None
        job_id = uuid4()
        inserted = await connection.fetchval(
            """
            insert into public.jobs (id, project_id, type, status, idempotency_key)
            values ($1, $2, $3, 'queued', $4)
            on conflict (project_id, type, idempotency_key) do nothing
            returning id
            """,
            job_id,
            project_id,
            job_type,
            idempotency_key,
        )
        if inserted is None:
            return await connection.fetchval(
                """
                select id from public.jobs
                where project_id = $1 and type = $2 and idempotency_key = $3
                """,
                project_id,
                job_type,
                idempotency_key,
            )
        await _create_outbox(connection, job_id, owner_id)
        return inserted


@pytest.mark.asyncio
async def test_reconstruction_job_and_outbox_intent_commit_together(database: str) -> None:
    project_id, owner_id = uuid4(), uuid4()
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "insert into public.projects (id, owner_id) values ($1, $2)", project_id, owner_id
        )
        job_id = await _create_job_with_outbox(
            connection,
            project_id=project_id,
            owner_id=owner_id,
            job_type="reconstruction",
            idempotency_key="reconstruction-key",
        )
        assert job_id is not None
        assert await connection.fetchval(
            "select count(*) from public.jobs where id = $1", job_id
        ) == 1
        assert await connection.fetchval(
            "select count(*) from public.submission_outbox where job_id = $1", job_id
        ) == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_conversion_job_and_outbox_intent_commit_together(database: str) -> None:
    project_id, owner_id = uuid4(), uuid4()
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "insert into public.projects (id, owner_id) values ($1, $2)", project_id, owner_id
        )
        job_id = await _create_job_with_outbox(
            connection,
            project_id=project_id,
            owner_id=owner_id,
            job_type="conversion",
            idempotency_key="conversion-key",
        )
        assert job_id is not None
        assert await connection.fetchval(
            "select count(*) from public.jobs where id = $1", job_id
        ) == 1
        assert await connection.fetchval(
            "select count(*) from public.submission_outbox where job_id = $1", job_id
        ) == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_job_and_outbox_roll_back_together(database: str) -> None:
    project_id, owner_id, job_id = uuid4(), uuid4(), uuid4()
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "insert into public.projects (id, owner_id) values ($1, $2)", project_id, owner_id
        )
        with pytest.raises(RuntimeError, match="force rollback"):
            async with connection.transaction():
                assert await _admit(connection) is True
                await connection.execute(
                    """
                    insert into public.jobs (id, project_id, type, status, idempotency_key)
                    values ($1, $2, 'reconstruction', 'queued', 'rollback-key')
                    """,
                    job_id,
                    project_id,
                )
                await _create_outbox(connection, job_id, owner_id)
                raise RuntimeError("force rollback")
        job_count = await connection.fetchval(
            "select count(*) from public.jobs where id = $1", job_id
        )
        assert job_count == 0
        assert (
            await connection.fetchval(
                "select count(*) from public.submission_outbox where job_id = $1", job_id
            )
            == 0
        )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_idempotency_replay_does_not_duplicate_outbox_intent(database: str) -> None:
    project_id, owner_id = uuid4(), uuid4()
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "insert into public.projects (id, owner_id) values ($1, $2)", project_id, owner_id
        )
        first_job_id = await _create_job_with_outbox(
            connection,
            project_id=project_id,
            owner_id=owner_id,
            job_type="reconstruction",
            idempotency_key="replay-key",
        )
        replayed_job_id = await _create_job_with_outbox(
            connection,
            project_id=project_id,
            owner_id=owner_id,
            job_type="reconstruction",
            idempotency_key="replay-key",
        )
        assert first_job_id == replayed_job_id
        assert await connection.fetchval(
            "select count(*) from public.submission_outbox where job_id = $1", first_job_id
        ) == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_draining_prevents_job_and_outbox_creation(database: str) -> None:
    project_id, owner_id = uuid4(), uuid4()
    connection = await asyncpg.connect(database)
    try:
        await connection.execute(
            "insert into public.projects (id, owner_id) values ($1, $2)", project_id, owner_id
        )
        await _begin(connection, uuid4(), uuid4())
        job_id = await _create_job_with_outbox(
            connection,
            project_id=project_id,
            owner_id=owner_id,
            job_type="conversion",
            idempotency_key="draining-key",
        )
        assert job_id is None
        assert await connection.fetchval("select count(*) from public.jobs") == 0
        assert await connection.fetchval("select count(*) from public.submission_outbox") == 0
    finally:
        await connection.close()
