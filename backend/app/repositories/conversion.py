from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.jobs import ConversionJob, WorkerConversionJob
from app.repositories.worker_attempt import AttemptAcquisition


class ConversionInitiationRejection(StrEnum):
    RELEASE_DRAINING = "release_draining"
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
        algorithm_version: str,
        idempotency_key: str,
    ) -> ConversionInitiation: ...

    async def get_for_worker(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> WorkerConversionJob | None: ...

    async def acquire_attempt(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        lease_seconds: int,
    ) -> AttemptAcquisition: ...

    async def is_release_draining(self) -> bool: ...

    async def recovery_time(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> datetime | None:
        """Return a queued/running job's active lease expiry or the current database time."""
        ...

    async def renew_attempt(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        attempt_id: UUID,
        lease_seconds: int,
    ) -> bool: ...

    async def release_attempt(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        attempt_id: UUID,
    ) -> None: ...

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        attempt_id: UUID,
        error_code: str,
        error_message: str,
    ) -> bool: ...

    async def finalize_success(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        attempt_id: UUID,
        artifact_id: UUID,
        blob_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> bool: ...

    async def mark_succeeded(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        attempt_id: UUID,
    ) -> bool: ...
