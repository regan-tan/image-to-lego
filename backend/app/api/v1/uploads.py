from datetime import timedelta
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import CurrentOwnerId
from app.core.auth import SettingsDependency
from app.core.config import Settings
from app.core.database import DatabaseSession
from app.core.errors import ApplicationError
from app.providers.blob_storage import BlobStorage
from app.repositories.sqlalchemy_uploads import SqlAlchemyUploadRepository
from app.repositories.uploads import UploadRepository
from app.services.uploads import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


class CreateUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: UUID = Field(alias="projectId")
    file_name: str = Field(alias="fileName")
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes")
    sha256: str


class CreateUploadResponse(BaseModel):
    upload_id: UUID = Field(serialization_alias="uploadId")
    project_id: UUID = Field(serialization_alias="projectId")
    status: Literal["pending"]
    upload_url: str = Field(serialization_alias="uploadUrl", repr=False)
    upload_url_expires_at: str = Field(serialization_alias="uploadUrlExpiresAt")
    required_headers: dict[str, str] = Field(serialization_alias="requiredHeaders")


class CompleteUploadResponse(BaseModel):
    upload_id: UUID = Field(serialization_alias="uploadId")
    project_id: UUID = Field(serialization_alias="projectId")
    status: Literal["ready"]


def get_upload_repository(session: DatabaseSession) -> UploadRepository:
    return SqlAlchemyUploadRepository(session)


def get_blob_storage(request: Request) -> BlobStorage:
    storage = cast(BlobStorage | None, getattr(request.app.state, "blob_storage", None))
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage is not configured.",
        )
    return storage


UploadRepositoryDependency = Annotated[UploadRepository, Depends(get_upload_repository)]
BlobStorageDependency = Annotated[BlobStorage, Depends(get_blob_storage)]


@router.post("", response_model=CreateUploadResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: CreateUploadRequest,
    owner_id: CurrentOwnerId,
    repository: UploadRepositoryDependency,
    blob_storage: BlobStorageDependency,
    settings: SettingsDependency,
) -> CreateUploadResponse:
    service = _upload_service(repository, blob_storage, settings)
    try:
        initiation = await service.initiate(
            owner_id=owner_id,
            project_id=request.project_id,
            file_name=request.file_name,
            mime_type=request.mime_type,
            size_bytes=request.size_bytes,
            sha256=request.sha256,
        )
    except ApplicationError as error:
        raise _upload_http_error(error) from error

    return CreateUploadResponse(
        upload_id=initiation.artifact.id,
        project_id=initiation.artifact.project_id,
        status="pending",
        upload_url=initiation.upload_url,
        upload_url_expires_at=initiation.upload_url_expires_at.isoformat(),
        required_headers=initiation.required_headers,
    )


@router.post("/{upload_id}/complete", response_model=CompleteUploadResponse)
async def complete_upload(
    upload_id: UUID,
    owner_id: CurrentOwnerId,
    repository: UploadRepositoryDependency,
    blob_storage: BlobStorageDependency,
    settings: SettingsDependency,
) -> CompleteUploadResponse:
    service = _upload_service(repository, blob_storage, settings)
    try:
        artifact = await service.complete(owner_id=owner_id, artifact_id=upload_id)
    except ApplicationError as error:
        raise _upload_http_error(error) from error
    return CompleteUploadResponse(
        upload_id=artifact.id,
        project_id=artifact.project_id,
        status="ready",
    )


def _upload_service(
    repository: UploadRepository,
    blob_storage: BlobStorage,
    settings: Settings,
) -> UploadService:
    return UploadService(
        repository=repository,
        blob_storage=blob_storage,
        max_image_size_bytes=settings.upload_max_image_size_bytes,
        quota_limit=settings.upload_quota_limit,
        quota_window=timedelta(hours=settings.upload_quota_window_hours),
        pending_lifetime=timedelta(hours=settings.upload_pending_lifetime_hours),
        sas_lifetime=timedelta(minutes=settings.upload_sas_lifetime_minutes),
    )


def _upload_http_error(error: ApplicationError) -> HTTPException:
    if error.code in {"project_not_found", "upload_not_found"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.message)
    if error.code == "image_too_large":
        return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=error.message)
    if error.code == "upload_quota_exceeded":
        retry_after = str(error.retry_after_seconds or 1)
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error.message,
            headers={"Retry-After": retry_after},
        )
    if error.code in {"upload_expired", "uploaded_blob_missing", "uploaded_blob_mismatch"}:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message)
    if error.code == "blob_storage_unavailable":
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error.message,
        )
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error.message)
