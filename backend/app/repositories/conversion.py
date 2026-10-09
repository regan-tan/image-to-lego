from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.jobs import ConversionJob, WorkerConversionJob


class ConversionInitiationRejection(StrEnum):
    NOT_FOUND = "not_found"
    WRONG_ARTIFACT_KIND = "wrong_artifact_kind"
    SOURCE_NOT_READY = "source_not_ready"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


@dataclass(frozen=True, slots=True)
class ConversionInitiation:
    conversion: ConversionJob | None = None
    created: bool = False
    rejection: ConversionInitiationRejection | None = None


class ConversionRepository(Protocol):
    async def create_or_get(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        source_artifact_id: UUID,
        target_parts: int,
        up_axis: str,
        idempotency_key: str,
    ) -> ConversionInitiation: ...

    async def mark_queue_publish_failed(self, *, job_id: UUID, owner_id: UUID) -> None: ...

    async def get_for_worker(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> WorkerConversionJob | None: ...

    async def claim(self, *, job_id: UUID, owner_id: UUID) -> bool: ...

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        error_code: str,
        error_message: str,
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
