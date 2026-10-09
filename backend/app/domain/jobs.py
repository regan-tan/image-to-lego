from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.artifacts import Artifact


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
    provider_job_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReconstructionJob:
    job: Job
    source_artifact_id: UUID
    output_artifact_id: UUID | None


@dataclass(frozen=True, slots=True)
class ConversionJob:
    job: Job
    source_artifact_id: UUID
    target_parts: int
    up_axis: str
    output_artifact_id: UUID | None


@dataclass(frozen=True, slots=True)
class WorkerReconstructionJob:
    reconstruction: ReconstructionJob
    owner_id: UUID
    source_artifact: Artifact


@dataclass(frozen=True, slots=True)
class WorkerConversionJob:
    conversion: ConversionJob
    owner_id: UUID
    source_artifact: Artifact


@dataclass(frozen=True, slots=True)
class JobStatusRecord:
    job: Job
    output_artifact_id: UUID | None
