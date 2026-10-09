from dataclasses import dataclass
from uuid import UUID

from app.conversion.core import MAX_TARGET_PARTS
from app.core.errors import ApplicationError
from app.domain.jobs import ConversionJob
from app.providers.conversion_queue import ConversionQueue, ConversionQueueError
from app.repositories.conversion import ConversionInitiationRejection, ConversionRepository

MAX_IDEMPOTENCY_KEY_LENGTH = 200


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    project_id: UUID
    source_artifact_id: UUID
    target_parts: int
    up_axis: str


class ConversionInitiationService:
    """Creates a durable conversion job before publishing its tiny queue message."""

    def __init__(
        self,
        *,
        repository: ConversionRepository,
        conversion_queue: ConversionQueue,
    ) -> None:
        self._repository = repository
        self._conversion_queue = conversion_queue

    async def initiate(
        self,
        *,
        owner_id: UUID,
        request: ConversionRequest,
        idempotency_key: str,
    ) -> tuple[ConversionJob, bool]:
        if request.target_parts <= 0:
            raise ApplicationError(
                code="invalid_target_parts",
                message="Target parts must be greater than zero.",
            )
        if request.target_parts > MAX_TARGET_PARTS:
            raise ApplicationError(
                code="invalid_target_parts",
                message="Target parts exceeds the configured safety limit.",
            )
        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ApplicationError(
                code="invalid_idempotency_key",
                message="Idempotency-Key must contain between 1 and 200 characters.",
            )
        created = await self._repository.create_or_get(
            owner_id=owner_id,
            project_id=request.project_id,
            source_artifact_id=request.source_artifact_id,
            target_parts=request.target_parts,
            up_axis=request.up_axis,
            idempotency_key=normalized_key,
        )
        if created.rejection is ConversionInitiationRejection.NOT_FOUND:
            raise ApplicationError(
                code="conversion_source_not_found",
                message="The project or reconstructed model does not exist.",
            )
        if created.rejection is ConversionInitiationRejection.WRONG_ARTIFACT_KIND:
            raise ApplicationError(
                code="invalid_conversion_source",
                message="The selected artifact is not a reconstructed model.",
            )
        if created.rejection is ConversionInitiationRejection.SOURCE_NOT_READY:
            raise ApplicationError(
                code="conversion_source_not_ready",
                message="The reconstructed model is not ready for conversion.",
            )
        if created.rejection is ConversionInitiationRejection.IDEMPOTENCY_CONFLICT:
            raise ApplicationError(
                code="idempotency_conflict",
                message="Idempotency-Key was already used for another conversion request.",
            )
        if created.conversion is None:
            raise RuntimeError("Conversion repository returned no result.")
        if not created.created:
            return created.conversion, False
        try:
            await self._conversion_queue.enqueue(
                job_id=created.conversion.job.id,
                owner_id=owner_id,
            )
        except ConversionQueueError as error:
            await self._repository.mark_queue_publish_failed(
                job_id=created.conversion.job.id,
                owner_id=owner_id,
            )
            raise ApplicationError(
                code="conversion_queue_unavailable",
                message="Conversion could not be started. Please try again.",
            ) from error
        return created.conversion, True
