from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import uuid4

import pytest

from app.repositories.worker_attempt import AttemptAcquisition, AttemptAcquisitionStatus
from app.workers.conversion_worker import _parse_message as parse_conversion_message
from app.workers.generation_worker import _parse_message as parse_generation_message

MessageParser = Callable[[Iterable[bytes]], tuple[object, object] | None]


def test_attempt_acquisition_requires_an_attempt_id_only_when_acquired() -> None:
    attempt_id = uuid4()
    acquired = AttemptAcquisition(AttemptAcquisitionStatus.ACQUIRED, attempt_id)
    blocked = AttemptAcquisition(AttemptAcquisitionStatus.RELEASE_BLOCKED)

    assert acquired.attempt_id == attempt_id
    assert blocked.attempt_id is None
    with pytest.raises(ValueError):
        AttemptAcquisition(AttemptAcquisitionStatus.ACQUIRED)
    with pytest.raises(ValueError):
        AttemptAcquisition(AttemptAcquisitionStatus.LEASE_HELD, attempt_id)


@pytest.mark.parametrize("parser", [parse_generation_message, parse_conversion_message])
def test_workers_accept_legacy_and_current_queue_messages(parser: MessageParser) -> None:
    job_id = uuid4()
    owner_id = uuid4()
    legacy = [f'{{"jobId":"{job_id}","ownerId":"{owner_id}"}}'.encode()]
    current = [
        f'{{"messageVersion":1,"jobId":"{job_id}","ownerId":"{owner_id}"}}'.encode()
    ]

    assert parser(legacy) == (job_id, owner_id)
    assert parser(current) == (job_id, owner_id)


@pytest.mark.parametrize("parser", [parse_generation_message, parse_conversion_message])
def test_workers_reject_an_unknown_queue_message_version(parser: MessageParser) -> None:
    body = [f'{{"messageVersion":2,"jobId":"{uuid4()}","ownerId":"{uuid4()}"}}'.encode()]

    assert parser(body) is None


def test_release_migration_serializes_gate_and_job_claims() -> None:
    migration = Path(
        "../supabase/migrations/20261102000000_durable_worker_release_coordination.sql"
    )
    content = migration.read_text(encoding="utf-8")

    assert "worker_release_state" in content
    assert "FOR UPDATE" in content
    assert "worker_release_try_acquire_attempt" in content
    assert "release_blocked" in content
    assert "worker_release_recover" in content
    assert "provider_job_id IS NULL" in content
