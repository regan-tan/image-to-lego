from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.jobs import ReconstructionJob, WorkerReconstructionJob


class ReconstructionInitiationRejection(StrEnum):
    NOT_FOUND = "not_found"
    WRONG_ARTIFACT_KIND = "wrong_artifact_kind"
    SOURCE_NOT_READY = "source_not_ready"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


@dataclass(frozen=True, slots=True)
class ReconstructionInitiation:
    reconstruction: ReconstructionJob | None = None
    created: bool = False
    rejection: ReconstructionInitiationRejection | None = None


class ReconstructionRepository(Protocol):
    async def create_or_get(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        source_artifact_id: UUID,
        idempotency_key: str,
    ) -> ReconstructionInitiation: ...

    async def mark_queue_publish_failed(self, *, job_id: UUID, owner_id: UUID) -> None: ...

    async def get_for_owner(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> ReconstructionJob | None: ...

    async def get_for_worker(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> WorkerReconstructionJob | None: ...

    async def claim_provider_submission(self, *, job_id: UUID, owner_id: UUID) -> bool: ...

    async def persist_provider_job_id(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        provider_job_id: str,
    ) -> None: ...

    async def mark_terminal(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    async def create_output_artifact(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        artifact_id: UUID,
        blob_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> UUID: ...

    async def mark_succeeded(self, *, job_id: UUID, owner_id: UUID) -> None: ...
