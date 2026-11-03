from uuid import UUID

from app.core.errors import ApplicationError
from app.domain.jobs import ReconstructionJob
from app.providers.reconstruction import (
    ReconstructionProvider,
    ReconstructionRequest,
    ReconstructionStatus,
    ReconstructionSubmission,
)
from app.repositories.reconstruction import (
    ReconstructionInitiationRejection,
    ReconstructionRepository,
)

MAX_IDEMPOTENCY_KEY_LENGTH = 200


class ReconstructionService:
    def __init__(self, provider: ReconstructionProvider) -> None:
        self._provider = provider

    async def submit(self, request: ReconstructionRequest) -> ReconstructionSubmission:
        return await self._provider.submit(request)

    async def get_status(self, provider_job_id: str) -> ReconstructionStatus:
        return await self._provider.get_status(provider_job_id)

    async def cancel(self, provider_job_id: str) -> ReconstructionStatus:
        return await self._provider.cancel(provider_job_id)


class ReconstructionInitiationService:
    """Creates a reconstruction job and durable publication intent."""

    def __init__(
        self,
        *,
        repository: ReconstructionRepository,
    ) -> None:
        self._repository = repository

    async def initiate(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        source_artifact_id: UUID,
        idempotency_key: str,
    ) -> tuple[ReconstructionJob, bool]:
        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ApplicationError(
                code="invalid_idempotency_key",
                message="Idempotency-Key must contain between 1 and 200 characters.",
            )
        created = await self._repository.create_or_get(
            owner_id=owner_id,
            project_id=project_id,
            source_artifact_id=source_artifact_id,
            idempotency_key=normalized_key,
        )
        if created.rejection is ReconstructionInitiationRejection.NOT_FOUND:
            raise ApplicationError(
                code="reconstruction_source_not_found",
                message="The project or source image does not exist.",
            )
        if created.rejection is ReconstructionInitiationRejection.RELEASE_DRAINING:
            raise ApplicationError(
                code="release_draining",
                message=(
                    "Job submissions are temporarily paused for maintenance. "
                    "Please retry later."
                ),
            )
        if created.rejection is ReconstructionInitiationRejection.WRONG_ARTIFACT_KIND:
            raise ApplicationError(
                code="invalid_reconstruction_source",
                message="The selected artifact is not a source image.",
            )
        if created.rejection is ReconstructionInitiationRejection.SOURCE_NOT_READY:
            raise ApplicationError(
                code="reconstruction_source_not_ready",
                message="The source image is not ready for reconstruction.",
            )
        if created.rejection is ReconstructionInitiationRejection.IDEMPOTENCY_CONFLICT:
            raise ApplicationError(
                code="idempotency_conflict",
                message="Idempotency-Key was already used for another reconstruction request.",
            )
        if created.reconstruction is None:
            raise RuntimeError("Reconstruction repository returned no result.")
        if not created.created:
            return created.reconstruction, False

        return created.reconstruction, True
