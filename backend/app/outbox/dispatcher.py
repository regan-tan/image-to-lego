"""A fail-closed dispatcher for durable submission outbox records."""

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


class OutboxClaimStatus(StrEnum):
    CLAIMED = "claimed"
    EMPTY = "empty"
    RELEASE_BLOCKED = "release_blocked"


@dataclass(frozen=True, slots=True)
class SubmissionOutboxClaim:
    outbox_id: UUID
    job_id: UUID
    owner_id: UUID
    message_type: str
    schema_version: int
    dispatch_fencing_token: int


@dataclass(frozen=True, slots=True)
class ClaimResult:
    status: OutboxClaimStatus
    claim: SubmissionOutboxClaim | None = None


@dataclass(frozen=True, slots=True)
class OutboxDispatcherConfig:
    claim_lease_seconds: int
    known_failure_retry_delay: timedelta


@dataclass(frozen=True, slots=True)
class DispatchRunResult:
    delivered_count: int
    known_failure_count: int
    uncertain_count: int
    release_blocked: bool


class SubmissionOutboxRepository(Protocol):
    async def mark_expired_sends_attention(self) -> int: ...
    async def claim(self, dispatcher_id: UUID, lease_seconds: int) -> ClaimResult: ...
    async def begin_send(self, claim: SubmissionOutboxClaim, dispatcher_id: UUID) -> bool: ...
    async def record_delivered(self, claim: SubmissionOutboxClaim, dispatcher_id: UUID) -> bool: ...
    async def record_known_failure(
        self,
        claim: SubmissionOutboxClaim,
        dispatcher_id: UUID,
        error_code: str,
        error_message: str,
        retry_at: datetime,
    ) -> bool: ...
    async def record_uncertain(
        self, claim: SubmissionOutboxClaim, dispatcher_id: UUID, reason: str
    ) -> bool: ...
    async def release_unstarted_claim(
        self, claim: SubmissionOutboxClaim, dispatcher_id: UUID
    ) -> bool: ...


class PublicationNotAttemptedError(Exception):
    """The transport proved it did not begin an external Service Bus send."""


class SubmissionMessageTransport(Protocol):
    async def publish(self, claim: SubmissionOutboxClaim) -> None: ...


class SubmissionOutboxDispatcher:
    """Claims and publishes a bounded number of intents without DB locks during I/O."""

    def __init__(
        self,
        repository: SubmissionOutboxRepository,
        transport: SubmissionMessageTransport,
        config: OutboxDispatcherConfig,
    ) -> None:
        self._repository = repository
        self._transport = transport
        self._config = config

    async def run_once(self, *, dispatcher_id: UUID, max_messages: int) -> DispatchRunResult:
        if max_messages <= 0:
            raise ValueError("max_messages must be positive")
        delivered_count = 0
        known_failure_count = 0
        uncertain_count = 0
        for _ in range(max_messages):
            await self._repository.mark_expired_sends_attention()
            result = await self._repository.claim(dispatcher_id, self._config.claim_lease_seconds)
            if result.status is OutboxClaimStatus.EMPTY:
                return DispatchRunResult(
                    delivered_count, known_failure_count, uncertain_count, False
                )
            if result.status is OutboxClaimStatus.RELEASE_BLOCKED:
                return DispatchRunResult(
                    delivered_count, known_failure_count, uncertain_count, True
                )
            if result.claim is None:
                raise RuntimeError("Outbox claim returned claimed without a publication intent.")
            outcome = await self._dispatch_claim(result.claim, dispatcher_id)
            if outcome == "delivered":
                delivered_count += 1
            elif outcome == "known_failure":
                known_failure_count += 1
            elif outcome == "uncertain":
                uncertain_count += 1
            elif outcome == "release_blocked":
                return DispatchRunResult(
                    delivered_count, known_failure_count, uncertain_count, True
                )
        return DispatchRunResult(delivered_count, known_failure_count, uncertain_count, False)

    async def _dispatch_claim(self, claim: SubmissionOutboxClaim, dispatcher_id: UUID) -> str:
        try:
            send_started = await self._repository.begin_send(claim, dispatcher_id)
        except asyncio.CancelledError:
            await self._finish(self._repository.release_unstarted_claim(claim, dispatcher_id))
            raise
        if not send_started:
            await self._repository.release_unstarted_claim(claim, dispatcher_id)
            return "release_blocked"
        try:
            await self._transport.publish(claim)
        except PublicationNotAttemptedError as error:
            await self._repository.record_known_failure(
                claim,
                dispatcher_id,
                "publication_not_attempted",
                _safe_error_message(error),
                datetime.now(UTC) + self._config.known_failure_retry_delay,
            )
            return "known_failure"
        except asyncio.CancelledError:
            await self._finish(
                self._repository.record_uncertain(
                    claim,
                    dispatcher_id,
                    "Dispatcher cancelled while Service Bus publication was unresolved.",
                )
            )
            raise
        except Exception as error:
            await self._repository.record_uncertain(
                claim,
                dispatcher_id,
                "Service Bus publication outcome was uncertain: " + _safe_error_message(error),
            )
            return "uncertain"
        await self._finish(self._repository.record_delivered(claim, dispatcher_id))
        return "delivered"

    async def _finish(self, operation: Awaitable[bool]) -> None:
        task: asyncio.Future[bool] = asyncio.ensure_future(operation)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(task)
            except Exception:
                logger.exception("Could not durably finish an already-started publication.")
            raise


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip()
    return message[:500] if message else type(error).__name__
