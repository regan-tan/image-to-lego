from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.domain.types import JsonValue


class ReconstructionState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class ReconstructionRequest:
    input_artifact_id: UUID
    model: str
    source_url: str = ""
    settings: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconstructionSubmission:
    provider_job_id: str
    state: ReconstructionState


@dataclass(frozen=True, slots=True)
class ReconstructionStatus:
    provider_job_id: str
    state: ReconstructionState
    output_urls: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ReconstructionOutput:
    """A model file URL returned by a completed provider request."""

    url: str
    mime_type: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
