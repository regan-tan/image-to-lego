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
)
TEST_DATABASE_NAME = "image_to_lego_test"
LOCAL_TEST_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


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
    await connection.execute(
        """
        drop schema public cascade;
        create schema public;
        create extension if not exists pgcrypto;
        create table public.projects (id uuid primary key, owner_id uuid not null);
        create table public.jobs (
            id uuid primary key,
            project_id uuid not null references public.projects(id),
            type text not null,
            status text not null,
            idempotency_key text,
            provider_job_id text,
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
        await connection.execute(_read_migration_sql(migration_directory / migration))
    yield database_url
    await connection.close()


@pytest.fixture
async def database(postgres_database: str) -> str:
    connection = await asyncpg.connect(postgres_database)
    await connection.execute(
        """
        truncate public.submission_outbox, public.jobs, public.projects,
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
