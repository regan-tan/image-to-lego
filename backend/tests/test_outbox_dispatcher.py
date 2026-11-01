from datetime import timedelta
from uuid import UUID, uuid4

from app.outbox.dispatcher import (
    ClaimResult,
    OutboxClaimStatus,
    OutboxDispatcherConfig,
    PublicationNotAttemptedError,
    SubmissionOutboxClaim,
    SubmissionOutboxDispatcher,
)


class FakeRepository:
    def __init__(self, claims: list[ClaimResult], begin_send: bool = True) -> None:
        self.claims = claims
        self.begin_send_result = begin_send
        self.claimed: list[UUID] = []
        self.begun: list[UUID] = []
        self.delivered: list[UUID] = []
        self.known_failures: list[UUID] = []
        self.uncertain: list[UUID] = []
        self.released: list[UUID] = []

    async def mark_expired_sends_attention(self) -> int:
        return 0

    async def claim(self, dispatcher_id: UUID, lease_seconds: int) -> ClaimResult:
        result = self.claims.pop(0) if self.claims else ClaimResult(OutboxClaimStatus.EMPTY)
        if result.claim is not None:
            self.claimed.append(result.claim.outbox_id)
        return result

    async def begin_send(self, claim: SubmissionOutboxClaim, dispatcher_id: UUID) -> bool:
        self.begun.append(claim.outbox_id)
        return self.begin_send_result

    async def record_delivered(self, claim: SubmissionOutboxClaim, dispatcher_id: UUID) -> bool:
        self.delivered.append(claim.outbox_id)
        return True

    async def record_known_failure(
        self,
        claim: SubmissionOutboxClaim,
        dispatcher_id: UUID,
        error_code: str,
        error_message: str,
        retry_at: object,
    ) -> bool:
        self.known_failures.append(claim.outbox_id)
        return True

    async def record_uncertain(
        self, claim: SubmissionOutboxClaim, dispatcher_id: UUID, reason: str
    ) -> bool:
        self.uncertain.append(claim.outbox_id)
        return True

    async def release_unstarted_claim(
        self, claim: SubmissionOutboxClaim, dispatcher_id: UUID
    ) -> bool:
        self.released.append(claim.outbox_id)
        return True


class FakeTransport:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.published: list[UUID] = []

    async def publish(self, claim: SubmissionOutboxClaim) -> None:
        self.published.append(claim.outbox_id)
        if self.error is not None:
            raise self.error


def _claim() -> SubmissionOutboxClaim:
    return SubmissionOutboxClaim(uuid4(), uuid4(), uuid4(), "reconstruction_job", 1, 1)


def _dispatcher(repository: FakeRepository, transport: FakeTransport) -> SubmissionOutboxDispatcher:
    return SubmissionOutboxDispatcher(
        repository,
        transport,
        OutboxDispatcherConfig(
            claim_lease_seconds=60, known_failure_retry_delay=timedelta(seconds=30)
        ),
    )


async def test_dispatcher_marks_confirmed_service_bus_send_delivered() -> None:
    claim = _claim()
    repository = FakeRepository([ClaimResult(OutboxClaimStatus.CLAIMED, claim)])
    transport = FakeTransport()

    result = await _dispatcher(repository, transport).run_once(
        dispatcher_id=uuid4(), max_messages=1
    )

    assert result.delivered_count == 1
    assert transport.published == [claim.outbox_id]
    assert repository.delivered == [claim.outbox_id]
    assert repository.uncertain == []


async def test_dispatcher_retries_a_failure_proven_before_send() -> None:
    claim = _claim()
    repository = FakeRepository([ClaimResult(OutboxClaimStatus.CLAIMED, claim)])
    transport = FakeTransport(PublicationNotAttemptedError("invalid local message"))

    result = await _dispatcher(repository, transport).run_once(
        dispatcher_id=uuid4(), max_messages=1
    )

    assert result.known_failure_count == 1
    assert repository.known_failures == [claim.outbox_id]
    assert repository.uncertain == []


async def test_dispatcher_marks_unexpected_service_bus_error_uncertain() -> None:
    claim = _claim()
    repository = FakeRepository([ClaimResult(OutboxClaimStatus.CLAIMED, claim)])
    transport = FakeTransport(TimeoutError("reply lost"))

    result = await _dispatcher(repository, transport).run_once(
        dispatcher_id=uuid4(), max_messages=1
    )

    assert result.uncertain_count == 1
    assert repository.uncertain == [claim.outbox_id]
    assert repository.delivered == []


async def test_concurrent_dispatchers_cannot_both_publish_one_claim() -> None:
    claim = _claim()
    first = FakeRepository([ClaimResult(OutboxClaimStatus.CLAIMED, claim)])
    second = FakeRepository([ClaimResult(OutboxClaimStatus.EMPTY)])
    first_transport = FakeTransport()
    second_transport = FakeTransport()

    await _dispatcher(first, first_transport).run_once(dispatcher_id=uuid4(), max_messages=1)
    await _dispatcher(second, second_transport).run_once(dispatcher_id=uuid4(), max_messages=1)

    assert first_transport.published == [claim.outbox_id]
    assert second_transport.published == []


async def test_draining_before_begin_send_releases_claim_without_publishing() -> None:
    claim = _claim()
    repository = FakeRepository([ClaimResult(OutboxClaimStatus.CLAIMED, claim)], begin_send=False)
    transport = FakeTransport()

    result = await _dispatcher(repository, transport).run_once(
        dispatcher_id=uuid4(), max_messages=1
    )

    assert result.release_blocked is True
    assert repository.released == [claim.outbox_id]
    assert transport.published == []
