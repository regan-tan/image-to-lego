from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import CurrentOwnerId
from app.core.database import DatabaseSession
from app.core.errors import ApplicationError
from app.domain.jobs import JobStatus
from app.domain.projects import Project, ProjectOverview, ProjectStatus
from app.repositories.projects import ProjectRepository
from app.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
from app.services.projects import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=100)


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    status: ProjectStatus
    source_image_artifact_id: UUID | None = Field(serialization_alias="sourceImageArtifactId")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class SourceImageResponse(BaseModel):
    artifact_id: UUID = Field(serialization_alias="artifactId")
    mime_type: str = Field(serialization_alias="mimeType")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    created_at: datetime = Field(serialization_alias="createdAt")


class LatestReconstructionResponse(BaseModel):
    job_id: UUID = Field(serialization_alias="jobId")
    status: JobStatus
    output_artifact_id: UUID | None = Field(serialization_alias="outputArtifactId")
    error_code: str | None = Field(serialization_alias="errorCode")
    error_message: str | None = Field(serialization_alias="errorMessage")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ProjectDetailResponse(ProjectResponse):
    source_image: SourceImageResponse | None = Field(serialization_alias="sourceImage")
    latest_reconstruction: LatestReconstructionResponse | None = Field(
        serialization_alias="latestReconstruction"
    )


def get_project_repository(session: DatabaseSession) -> ProjectRepository:
    return SqlAlchemyProjectRepository(session)


ProjectRepositoryDependency = Annotated[ProjectRepository, Depends(get_project_repository)]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: CreateProjectRequest,
    owner_id: CurrentOwnerId,
    repository: ProjectRepositoryDependency,
) -> ProjectResponse:
    try:
        project = await ProjectService(repository).create(owner_id=owner_id, name=request.name)
    except ApplicationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error.message,
        ) from error
    # A project that was just created cannot have a source image yet.
    return _project_response(project, ProjectStatus.NEEDS_PHOTO, source_image_artifact_id=None)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    owner_id: CurrentOwnerId,
    repository: ProjectRepositoryDependency,
) -> list[ProjectResponse]:
    overviews = await ProjectService(repository).list_overviews_for_owner(owner_id=owner_id)
    return [
        _project_response(
            overview.project,
            overview.status,
            source_image_artifact_id=(
                overview.source_image.artifact_id if overview.source_image is not None else None
            ),
        )
        for overview in overviews
    ]


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    owner_id: CurrentOwnerId,
    repository: ProjectRepositoryDependency,
) -> ProjectDetailResponse:
    overview = await ProjectService(repository).get_overview_for_owner(
        project_id=project_id,
        owner_id=owner_id,
    )
    if overview is None:
        # Another user's project is reported exactly like a missing one, so IDs reveal nothing.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The project does not exist.",
        )
    return _project_detail_response(overview)


def _project_response(
    project: Project,
    project_status: ProjectStatus,
    *,
    source_image_artifact_id: UUID | None,
) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        status=project_status,
        source_image_artifact_id=source_image_artifact_id,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _project_detail_response(overview: ProjectOverview) -> ProjectDetailResponse:
    project = overview.project
    source_image = overview.source_image
    reconstruction = overview.reconstruction
    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        status=overview.status,
        source_image_artifact_id=source_image.artifact_id if source_image is not None else None,
        created_at=project.created_at,
        updated_at=project.updated_at,
        source_image=(
            SourceImageResponse(
                artifact_id=source_image.artifact_id,
                mime_type=source_image.mime_type,
                size_bytes=source_image.size_bytes,
                created_at=source_image.created_at,
            )
            if source_image is not None
            else None
        ),
        latest_reconstruction=(
            LatestReconstructionResponse(
                job_id=reconstruction.job_id,
                status=reconstruction.status,
                output_artifact_id=reconstruction.output_artifact_id,
                error_code=reconstruction.error_code,
                error_message=reconstruction.error_message,
                created_at=reconstruction.created_at,
                updated_at=reconstruction.updated_at,
            )
            if reconstruction is not None
            else None
        ),
    )
