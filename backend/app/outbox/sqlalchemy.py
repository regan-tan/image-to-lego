"""SQLAlchemy access to the private submission-outbox SQL protocol."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.outbox.dispatcher import ClaimResult, OutboxClaimStatus, SubmissionOutboxClaim

_DISPATCHER_ROLE = "image_to_lego_outbox_dispatcher"


class SqlAlchemySubmissionOutboxRepository:
    """Uses only fenced SECURITY DEFINER operations under the dedicated role."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def mark_expired_sends_attention(self) -> int:
        return cast(
            int,
            await self._scalar("select public.submission_outbox_mark_expired_sends_attention()"),
        )

    async def claim(self, dispatcher_id: UUID, lease_seconds: int) -> ClaimResult:
        async with self._session_factory() as session, session.begin():
            await _set_dispatcher_role(session)
            result = await session.execute(
                text(
                    "select * from public.submission_outbox_claim(:dispatcher_id, :lease_seconds)"
                ),
                {"dispatcher_id": dispatcher_id, "lease_seconds": lease_seconds},
            )
            row = result.mappings().one()
        status = OutboxClaimStatus(cast(str, row["status"]))
        if status is not OutboxClaimStatus.CLAIMED:
            return ClaimResult(status)
        return ClaimResult(status, _claim_from_row(row))

    async def begin_send(self, claim: SubmissionOutboxClaim, dispatcher_id: UUID) -> bool:
        return bool(await self._claim_scalar("submission_outbox_begin_send", claim, dispatcher_id))

    async def record_delivered(self, claim: SubmissionOutboxClaim, dispatcher_id: UUID) -> bool:
        return bool(
            await self._claim_scalar("submission_outbox_record_delivered", claim, dispatcher_id)
        )

    async def record_known_failure(
        self,
        claim: SubmissionOutboxClaim,
        dispatcher_id: UUID,
        error_code: str,
        error_message: str,
        retry_at: datetime,
    ) -> bool:
        return bool(
            await self._claim_scalar(
                "submission_outbox_record_known_failure",
                claim,
                dispatcher_id,
                error_code=error_code,
                error_message=error_message,
                retry_at=retry_at,
            )
        )

    async def record_uncertain(
        self, claim: SubmissionOutboxClaim, dispatcher_id: UUID, reason: str
    ) -> bool:
        return bool(
            await self._claim_scalar(
                "submission_outbox_record_uncertain", claim, dispatcher_id, reason=reason
            )
        )

    async def release_unstarted_claim(
        self, claim: SubmissionOutboxClaim, dispatcher_id: UUID
    ) -> bool:
        return bool(
            await self._claim_scalar(
                "submission_outbox_release_unstarted_claim", claim, dispatcher_id
            )
        )

    async def _claim_scalar(
        self,
        function_name: str,
        claim: SubmissionOutboxClaim,
        dispatcher_id: UUID,
        **extra_parameters: object,
    ) -> object:
        names = ["outbox_id", "dispatcher_id", "dispatch_fencing_token", *extra_parameters]
        parameters: dict[str, object] = {
            "outbox_id": claim.outbox_id,
            "dispatcher_id": dispatcher_id,
            "dispatch_fencing_token": claim.dispatch_fencing_token,
            **extra_parameters,
        }
        placeholders = ", ".join(f":{name}" for name in names)
        return await self._scalar(f"select public.{function_name}({placeholders})", parameters)

    async def _scalar(self, query: str, parameters: dict[str, object] | None = None) -> object:
        async with self._session_factory() as session, session.begin():
            await _set_dispatcher_role(session)
            result = await session.execute(text(query), parameters or {})
            return result.scalar_one()


async def _set_dispatcher_role(session: AsyncSession) -> None:
    # The role is NOINHERIT. It is selected only for this transaction; it has
    # EXECUTE rights on the private outbox functions, not general table access.
    await session.execute(text(f"set local role {_DISPATCHER_ROLE}"))


def _claim_from_row(row: RowMapping) -> SubmissionOutboxClaim:
    return SubmissionOutboxClaim(
        outbox_id=cast(UUID, row["outbox_id"]),
        job_id=cast(UUID, row["job_id"]),
        owner_id=cast(UUID, row["owner_id"]),
        message_type=cast(str, row["message_type"]),
        schema_version=cast(int, row["schema_version"]),
        dispatch_fencing_token=cast(int, row["dispatch_fencing_token"]),
    )
