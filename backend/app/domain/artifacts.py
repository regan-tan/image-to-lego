from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ArtifactStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class Artifact:
    id: UUID
    project_id: UUID
    kind: str
    blob_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: ArtifactStatus
    expires_at: datetime | None
    created_at: datetime
