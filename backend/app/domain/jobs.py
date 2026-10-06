from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class JobType(StrEnum):
    RECONSTRUCTION = "reconstruction"
    CONVERSION = "conversion"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class Job:
    id: UUID
    project_id: UUID
    type: JobType
    status: JobStatus
    idempotency_key: str
