from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import CurrentOwnerId
from app.core.database import DatabaseSession
from app.core.errors import ApplicationError
from app.domain.projects import Project
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
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


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
    return _project_response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    owner_id: CurrentOwnerId,
    repository: ProjectRepositoryDependency,
) -> list[ProjectResponse]:
    projects = await ProjectService(repository).list_for_owner(owner_id=owner_id)
    return [_project_response(project) for project in projects]


def _project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
