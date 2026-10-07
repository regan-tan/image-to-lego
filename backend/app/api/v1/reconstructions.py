from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import CurrentOwnerId
from app.core.database import DatabaseSession
from app.core.errors import ApplicationError
from app.domain.jobs import ReconstructionJob
from app.providers.generation_queue import GenerationQueue
from app.repositories.reconstruction import ReconstructionRepository
from app.repositories.sqlalchemy_reconstruction import SqlAlchemyReconstructionRepository
from app.services.reconstruction import ReconstructionInitiationService

router = APIRouter(tags=["reconstructions"])


class CreateReconstructionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: UUID = Field(alias="projectId")
    source_artifact_id: UUID = Field(alias="sourceArtifactId")


class ReconstructionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: UUID = Field(serialization_alias="jobId")
    project_id: UUID = Field(serialization_alias="projectId")
    type: Literal["reconstruction"]
    status: Literal["queued", "running", "succeeded", "failed", "canceled"]


class JobResponse(ReconstructionResponse):
    output_artifact_id: UUID | None = Field(serialization_alias="outputArtifactId")
    error_code: str | None = Field(serialization_alias="errorCode")
    error_message: str | None = Field(serialization_alias="errorMessage")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


def get_reconstruction_repository(session: DatabaseSession) -> ReconstructionRepository:
    return SqlAlchemyReconstructionRepository(session)


def get_generation_queue(request: Request) -> GenerationQueue:
    queue = cast(GenerationQueue | None, getattr(request.app.state, "generation_queue", None))
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation processing is not configured.",
        )
    return queue


ReconstructionRepositoryDependency = Annotated[
    ReconstructionRepository,
    Depends(get_reconstruction_repository),
]
GenerationQueueDependency = Annotated[GenerationQueue, Depends(get_generation_queue)]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.post("/reconstructions", response_model=ReconstructionResponse)
async def create_reconstruction(
    request: CreateReconstructionRequest,
    owner_id: CurrentOwnerId,
    idempotency_key: IdempotencyKey,
    repository: ReconstructionRepositoryDependency,
    generation_queue: GenerationQueueDependency,
) -> JSONResponse:
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key is required.",
        )
    try:
        reconstruction, created = await ReconstructionInitiationService(
            repository=repository,
            generation_queue=generation_queue,
        ).initiate(
            owner_id=owner_id,
            project_id=request.project_id,
            source_artifact_id=request.source_artifact_id,
            idempotency_key=idempotency_key,
        )
    except ApplicationError as error:
        raise _http_error(error) from error
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content=_reconstruction_response(reconstruction).model_dump(mode="json", by_alias=True),
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    owner_id: CurrentOwnerId,
    repository: ReconstructionRepositoryDependency,
) -> JobResponse:
    reconstruction = await repository.get_for_owner(job_id=job_id, owner_id=owner_id)
    if reconstruction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The job does not exist.")
    return _job_response(reconstruction)


def _reconstruction_response(reconstruction: ReconstructionJob) -> ReconstructionResponse:
    return ReconstructionResponse(
        job_id=reconstruction.job.id,
        project_id=reconstruction.job.project_id,
        type="reconstruction",
        status=reconstruction.job.status.value,
    )


def _job_response(reconstruction: ReconstructionJob) -> JobResponse:
    return JobResponse(
        **_reconstruction_response(reconstruction).model_dump(),
        output_artifact_id=reconstruction.output_artifact_id,
        error_code=reconstruction.job.error_code,
        error_message=reconstruction.job.error_message,
        created_at=reconstruction.job.created_at,
        updated_at=reconstruction.job.updated_at,
    )


def _http_error(error: ApplicationError) -> HTTPException:
    if error.code == "reconstruction_source_not_found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.message)
    if error.code in {
        "reconstruction_source_not_ready",
        "idempotency_conflict",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message)
    if error.code == "generation_queue_unavailable":
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=error.message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error.message)
