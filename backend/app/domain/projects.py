from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.jobs import JobStatus


@dataclass(frozen=True, slots=True)
class Project:
    id: UUID
    owner_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ProjectStatus(StrEnum):
    NEEDS_PHOTO = "needs_photo"
    PHOTO_READY = "photo_ready"
    GENERATING = "generating"
    MODEL_READY = "model_ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProjectSourceImage:
    """The project's most recent source image whose upload is ready."""

    artifact_id: UUID
    mime_type: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectReconstruction:
    """The most recent reconstruction job started from the project's current source image."""

    job_id: UUID
    status: JobStatus
    output_artifact_id: UUID | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectOverview:
    project: Project
    source_image: ProjectSourceImage | None
    reconstruction: ProjectReconstruction | None

    @property
    def status(self) -> ProjectStatus:
        return project_status(self.source_image, self.reconstruction)


_PROJECT_STATUS_BY_JOB_STATUS = {
    JobStatus.QUEUED: ProjectStatus.GENERATING,
    JobStatus.RUNNING: ProjectStatus.GENERATING,
    JobStatus.SUCCEEDED: ProjectStatus.MODEL_READY,
    JobStatus.FAILED: ProjectStatus.FAILED,
    # A canceled job leaves the user with the same next step as a failed one: try again.
    JobStatus.CANCELED: ProjectStatus.FAILED,
}


def project_status(
    source_image: ProjectSourceImage | None,
    reconstruction: ProjectReconstruction | None,
) -> ProjectStatus:
    if source_image is None:
        return ProjectStatus.NEEDS_PHOTO
    if reconstruction is None:
        return ProjectStatus.PHOTO_READY
    return _PROJECT_STATUS_BY_JOB_STATUS[reconstruction.status]
