from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import CurrentOwnerId
from app.core.database import DatabaseSession
from app.core.errors import ApplicationError
from app.domain.jobs import ConversionJob
from app.providers.conversion_queue import ConversionQueue
from app.repositories.conversion import ConversionRepository
from app.repositories.sqlalchemy_conversion import SqlAlchemyConversionRepository
from app.services.conversion import ConversionInitiationService, ConversionRequest

router = APIRouter(tags=["conversions"])


class CreateConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: UUID = Field(alias="projectId")
    source_artifact_id: UUID = Field(alias="sourceArtifactId")
    target_parts: int = Field(alias="targetParts")
    up_axis: Literal["x", "y", "z"] = Field(alias="upAxis")


class ConversionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: UUID = Field(serialization_alias="jobId")
    project_id: UUID = Field(serialization_alias="projectId")
    type: Literal["conversion"]
    status: Literal["queued", "running", "succeeded", "failed", "canceled"]


def get_conversion_repository(session: DatabaseSession) -> ConversionRepository:
    return SqlAlchemyConversionRepository(session)


def get_conversion_queue(request: Request) -> ConversionQueue:
    queue = cast(ConversionQueue | None, getattr(request.app.state, "conversion_queue", None))
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversion processing is not configured.",
        )
    return queue


ConversionRepositoryDependency = Annotated[ConversionRepository, Depends(get_conversion_repository)]
ConversionQueueDependency = Annotated[ConversionQueue, Depends(get_conversion_queue)]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.post("/conversions", response_model=ConversionResponse)
async def create_conversion(
    request: CreateConversionRequest,
    owner_id: CurrentOwnerId,
    idempotency_key: IdempotencyKey,
    repository: ConversionRepositoryDependency,
    conversion_queue: ConversionQueueDependency,
) -> JSONResponse:
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key is required.",
        )
    try:
        conversion, created = await ConversionInitiationService(
            repository=repository,
            conversion_queue=conversion_queue,
        ).initiate(
            owner_id=owner_id,
            request=ConversionRequest(
                project_id=request.project_id,
                source_artifact_id=request.source_artifact_id,
                target_parts=request.target_parts,
                up_axis=request.up_axis,
            ),
            idempotency_key=idempotency_key,
        )
    except ApplicationError as error:
        raise _http_error(error) from error
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content=_conversion_response(conversion).model_dump(mode="json", by_alias=True),
    )


def _conversion_response(conversion: ConversionJob) -> ConversionResponse:
    return ConversionResponse(
        job_id=conversion.job.id,
        project_id=conversion.job.project_id,
        type="conversion",
        status=conversion.job.status.value,
    )


def _http_error(error: ApplicationError) -> HTTPException:
    if error.code == "conversion_source_not_found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.message)
    if error.code in {
        "conversion_source_not_ready",
        "idempotency_conflict",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message)
    if error.code == "conversion_queue_unavailable":
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=error.message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error.message)
