from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentOwnerId
from app.api.v1.uploads import BlobStorageDependency
from app.core.auth import SettingsDependency
from app.core.database import DatabaseSession
from app.core.errors import ApplicationError
from app.repositories.artifacts import ArtifactRepository
from app.repositories.sqlalchemy_uploads import SqlAlchemyUploadRepository
from app.services.artifacts import ArtifactAccessService

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactReadUrlResponse(BaseModel):
    url: str = Field(repr=False)
    expires_at: datetime = Field(serialization_alias="expiresAt")


def get_artifact_repository(session: DatabaseSession) -> ArtifactRepository:
    # The upload repository's owner-scoped lookup already returns artifacts of every kind.
    return SqlAlchemyUploadRepository(session)


ArtifactRepositoryDependency = Annotated[ArtifactRepository, Depends(get_artifact_repository)]


@router.get("/{artifact_id}/read-url", response_model=ArtifactReadUrlResponse)
async def create_artifact_read_url(
    artifact_id: UUID,
    owner_id: CurrentOwnerId,
    repository: ArtifactRepositoryDependency,
    blob_storage: BlobStorageDependency,
    settings: SettingsDependency,
    response: Response,
    download: bool = False,
) -> ArtifactReadUrlResponse:
    service = ArtifactAccessService(
        repository=repository,
        blob_storage=blob_storage,
        read_url_lifetime=timedelta(minutes=settings.artifact_read_url_lifetime_minutes),
    )
    try:
        read_url = await service.create_read_url(
            owner_id=owner_id,
            artifact_id=artifact_id,
            download=download,
        )
    except ApplicationError as error:
        raise _artifact_http_error(error) from error

    # The signed URL is a short-lived credential; never let a browser or proxy cache it.
    response.headers["Cache-Control"] = "no-store"
    return ArtifactReadUrlResponse(url=read_url.url, expires_at=read_url.expires_at)


def _artifact_http_error(error: ApplicationError) -> HTTPException:
    if error.code == "artifact_not_found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.message)
    if error.code == "artifact_not_ready":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=error.message)
