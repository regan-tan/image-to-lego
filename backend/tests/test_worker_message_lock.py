import asyncio
import logging
from datetime import timedelta

import pytest
from azure.servicebus.exceptions import AutoLockRenewFailed, MessageLockLostError
from pydantic import ValidationError

from app.core.config import Settings
from app.workers import message_lock


class FakeMessage:
    pass


class FakeReceiver:
    def __init__(self, *, complete_error: Exception | None = None) -> None:
        self.complete_error = complete_error
        self.completed: list[FakeMessage] = []
        self.abandoned: list[FakeMessage] = []

    async def complete_message(self, message: FakeMessage) -> None:
        if self.complete_error is not None:
            raise self.complete_error
        self.completed.append(message)

    async def abandon_message(self, message: FakeMessage) -> None:
        self.abandoned.append(message)


class FakeAutoLockRenewer:
    instances: list["FakeAutoLockRenewer"] = []

    def __init__(self, *, max_lock_renewal_duration: float, on_lock_renew_failure: object) -> None:
        self.max_lock_renewal_duration = max_lock_renewal_duration
        self.on_lock_renew_failure = on_lock_renew_failure
        self.registered = False
        self.closed = False
        type(self).instances.append(self)

    async def __aenter__(self) -> "FakeAutoLockRenewer":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.closed = True

    def register(self, _: FakeReceiver, __: FakeMessage) -> None:
        self.registered = True


class FailingAutoLockRenewer(FakeAutoLockRenewer):
    def register(self, receiver: FakeReceiver, message: FakeMessage) -> None:
        super().register(receiver, message)
        callback = self.on_lock_renew_failure
        assert callable(callback)
        asyncio.create_task(callback(message, AutoLockRenewFailed("renewal failed")))


@pytest.fixture(autouse=True)
def reset_renewer_instances() -> None:
    FakeAutoLockRenewer.instances = []
    FailingAutoLockRenewer.instances = []


def renewer_patch(monkeypatch: pytest.MonkeyPatch, renewer: type[FakeAutoLockRenewer]) -> None:
    monkeypatch.setattr(message_lock, "AutoLockRenewer", renewer)


@pytest.mark.asyncio
async def test_successful_processing_renews_then_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=90),
        process=_succeeds,
        logger=logging.getLogger(__name__),
        job_description="conversion job",
    )

    renewer = FakeAutoLockRenewer.instances[0]
    assert renewer.registered
    assert renewer.max_lock_renewal_duration == 90
    assert renewer.closed
    assert receiver.completed == [message]
    assert receiver.abandoned == []


@pytest.mark.asyncio
async def test_long_processing_keeps_lock_renewer_active(monkeypatch: pytest.MonkeyPatch) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def process() -> None:
        started.set()
        await finish.wait()

    task = asyncio.create_task(
        message_lock.process_received_message(
            receiver=receiver,  # type: ignore[arg-type]
            message=message,  # type: ignore[arg-type]
            max_processing_duration=timedelta(seconds=90),
            process=process,
            logger=logging.getLogger(__name__),
            job_description="conversion job",
        )
    )
    await started.wait()

    renewer = FakeAutoLockRenewer.instances[0]
    assert renewer.registered
    assert not renewer.closed
    assert receiver.completed == []

    finish.set()
    await task
    assert receiver.completed == [message]


@pytest.mark.asyncio
async def test_renewal_failure_cancels_processing_without_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renewer_patch(monkeypatch, FailingAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()
    cancelled = asyncio.Event()

    async def process() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=90),
        process=process,
        logger=logging.getLogger(__name__),
        job_description="generation job",
    )

    assert cancelled.is_set()
    assert receiver.completed == []
    assert receiver.abandoned == []


@pytest.mark.asyncio
async def test_attempt_lease_renewal_failure_cancels_without_acknowledging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    cancelled = asyncio.Event()

    async def process() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def renew_attempt() -> bool:
        return False

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=FakeMessage(),  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=90),
        process=process,
        logger=logging.getLogger(__name__),
        job_description="conversion job",
        renew_attempt=renew_attempt,
        attempt_renewal_interval=timedelta(milliseconds=1),
    )

    assert cancelled.is_set()
    assert receiver.completed == []
    assert receiver.abandoned == []


@pytest.mark.asyncio
async def test_lock_expiry_does_not_abandon_or_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver(complete_error=MessageLockLostError())
    message = FakeMessage()

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=90),
        process=_succeeds,
        logger=logging.getLogger(__name__),
        job_description="generation job",
    )

    assert receiver.completed == []
    assert receiver.abandoned == []


@pytest.mark.asyncio
async def test_redelivery_can_complete_an_idempotent_job(monkeypatch: pytest.MonkeyPatch) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    stored = False
    writes = 0

    async def process() -> None:
        nonlocal stored, writes
        if stored:
            return
        stored = True
        writes += 1

    first_delivery = FakeReceiver(complete_error=MessageLockLostError())
    await message_lock.process_received_message(
        receiver=first_delivery,  # type: ignore[arg-type]
        message=FakeMessage(),  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=90),
        process=process,
        logger=logging.getLogger(__name__),
        job_description="conversion job",
    )
    redelivery = FakeReceiver()
    redelivered_message = FakeMessage()
    await message_lock.process_received_message(
        receiver=redelivery,  # type: ignore[arg-type]
        message=redelivered_message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=90),
        process=process,
        logger=logging.getLogger(__name__),
        job_description="conversion job",
    )

    assert writes == 1
    assert redelivery.completed == [redelivered_message]


@pytest.mark.asyncio
async def test_processing_exception_is_abandoned_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()

    async def process() -> None:
        raise RuntimeError("temporary database failure")

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=90),
        process=process,
        logger=logging.getLogger(__name__),
        job_description="generation job",
    )

    assert receiver.completed == []
    assert receiver.abandoned == [message]


@pytest.mark.asyncio
async def test_durable_recovery_scheduling_completes_the_current_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()
    scheduled = asyncio.Event()

    async def schedule_recovery() -> None:
        scheduled.set()

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=60),
        process=schedule_recovery,
        logger=logging.getLogger(__name__),
        job_description="conversion lease recovery",
    )

    assert scheduled.is_set()
    assert receiver.completed == [message]


@pytest.mark.asyncio
async def test_failed_recovery_scheduling_leaves_message_unsettled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()

    async def schedule_recovery() -> None:
        raise message_lock.LeaveMessageUnsettled()

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(seconds=60),
        process=schedule_recovery,
        logger=logging.getLogger(__name__),
        job_description="conversion lease recovery",
    )

    assert receiver.completed == []
    assert receiver.abandoned == []


@pytest.mark.asyncio
async def test_processing_deadline_abandons_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()
    cancelled = asyncio.Event()

    async def process() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    await message_lock.process_received_message(
        receiver=receiver,  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        max_processing_duration=timedelta(milliseconds=1),
        process=process,
        logger=logging.getLogger(__name__),
        job_description="conversion job",
    )

    assert cancelled.is_set()
    assert receiver.completed == []
    assert receiver.abandoned == [message]


@pytest.mark.asyncio
async def test_shutdown_cancels_processing_without_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renewer_patch(monkeypatch, FakeAutoLockRenewer)
    receiver = FakeReceiver()
    message = FakeMessage()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def process() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(
        message_lock.process_received_message(
            receiver=receiver,  # type: ignore[arg-type]
            message=message,  # type: ignore[arg-type]
            max_processing_duration=timedelta(seconds=90),
            process=process,
            logger=logging.getLogger(__name__),
            job_description="conversion job",
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled.is_set()
    assert receiver.completed == []
    assert receiver.abandoned == []
    assert FakeAutoLockRenewer.instances[0].closed


def test_lock_renewal_duration_has_explicit_safe_limits() -> None:
    assert Settings().service_bus_max_lock_renewal_seconds == 900
    with pytest.raises(ValidationError):
        Settings(service_bus_max_lock_renewal_seconds=59)
    with pytest.raises(ValidationError):
        Settings(service_bus_max_lock_renewal_seconds=3601)


async def _succeeds() -> None:
    return None
