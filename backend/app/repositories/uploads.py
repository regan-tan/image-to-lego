from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.artifacts import Artifact


class PendingUploadRejection(StrEnum):
    PROJECT_NOT_FOUND = "project_not_found"
    QUOTA_EXCEEDED = "quota_exceeded"


@dataclass(frozen=True, slots=True)
class PendingUploadResult:
    artifact: Artifact | None = None
    rejection: PendingUploadRejection | None = None
    retry_at: datetime | None = None


class UploadRepository(Protocol):
    async def create_pending(
        self,
        *,
        artifact_id: UUID,
        owner_id: UUID,
        project_id: UUID,
        blob_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        expires_at: datetime,
        quota_started_at: datetime,
        quota_window: timedelta,
        quota_limit: int,
    ) -> PendingUploadResult: ...

    async def get_for_owner(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None: ...

    async def mark_ready(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None: ...
