from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_database_owner
from app.domain.artifacts import Artifact, ArtifactStatus
from app.domain.jobs import Job, JobStatus, JobType, ReconstructionJob, WorkerReconstructionJob
from app.repositories.reconstruction import (
    ReconstructionInitiation,
    ReconstructionInitiationRejection,
)


class SqlAlchemyReconstructionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        source_artifact_id: UUID,
        idempotency_key: str,
    ) -> ReconstructionInitiation:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            project = await self._session.execute(
                text(
                    "select id from public.projects where id = :project_id and owner_id = :owner_id"
                ),
                {"project_id": project_id, "owner_id": owner_id},
            )
            if project.scalar_one_or_none() is None:
                return ReconstructionInitiation(
                    rejection=ReconstructionInitiationRejection.NOT_FOUND
                )

            artifact_result = await self._session.execute(
                text(
                    """
                    select id as source_id, project_id as source_project_id,
                           kind as source_kind, blob_name as source_blob_name,
                           mime_type as source_mime_type, size_bytes as source_size_bytes,
                           sha256 as source_sha256, status as source_status,
                           expires_at as source_expires_at, created_at as source_created_at
                    from public.artifacts
                    where id = :artifact_id and project_id = :project_id
                    """
                ),
                {"artifact_id": source_artifact_id, "project_id": project_id},
            )
            artifact_row = artifact_result.mappings().one_or_none()
            if artifact_row is None:
                return ReconstructionInitiation(
                    rejection=ReconstructionInitiationRejection.NOT_FOUND
                )
            artifact = _artifact_from_row(artifact_row)
            if artifact.kind != "source_image":
                return ReconstructionInitiation(
                    rejection=ReconstructionInitiationRejection.WRONG_ARTIFACT_KIND
                )
            if artifact.status is not ArtifactStatus.READY:
                return ReconstructionInitiation(
                    rejection=ReconstructionInitiationRejection.SOURCE_NOT_READY
                )

            existing = await self._get_by_idempotency(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                if existing.source_artifact_id != source_artifact_id:
                    return ReconstructionInitiation(
                        rejection=ReconstructionInitiationRejection.IDEMPOTENCY_CONFLICT
                    )
                return ReconstructionInitiation(reconstruction=existing)

            job_id = uuid4()
            inserted = await self._session.execute(
                text(
                    """
                    insert into public.jobs (id, project_id, type, status, idempotency_key)
                    values (:job_id, :project_id, 'reconstruction', 'queued', :idempotency_key)
                    on conflict (project_id, type, idempotency_key) do nothing
                    returning id, project_id, type, status, idempotency_key, provider_job_id,
                              error_code, error_message, created_at, updated_at
                    """
                ),
                {
                    "job_id": job_id,
                    "project_id": project_id,
                    "idempotency_key": idempotency_key,
                },
            )
            row = inserted.mappings().one_or_none()
            if row is None:
                existing = await self._get_by_idempotency(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                )
                if existing is None:
                    raise RuntimeError("Could not read the conflicting reconstruction job.")
                if existing.source_artifact_id != source_artifact_id:
                    return ReconstructionInitiation(
                        rejection=ReconstructionInitiationRejection.IDEMPOTENCY_CONFLICT
                    )
                return ReconstructionInitiation(reconstruction=existing)

            await self._session.execute(
                text(
                    """
                    insert into public.reconstruction_runs (
                        job_id, input_artifact_id, provider, model
                    )
                    values (:job_id, :source_artifact_id, 'fal', 'fal-ai/trellis')
                    """
                ),
                {"job_id": job_id, "source_artifact_id": source_artifact_id},
            )
            return ReconstructionInitiation(
                reconstruction=ReconstructionJob(
                    job=_job_from_row(row),
                    source_artifact_id=source_artifact_id,
                    output_artifact_id=None,
                ),
                created=True,
            )

    async def mark_queue_publish_failed(self, *, job_id: UUID, owner_id: UUID) -> None:
        await self.mark_terminal(
            job_id=job_id,
            owner_id=owner_id,
            status=JobStatus.FAILED.value,
            error_code="generation_queue_unavailable",
            error_message="Generation could not be queued. Please start it again.",
        )

    async def get_for_owner(self, *, job_id: UUID, owner_id: UUID) -> ReconstructionJob | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    _RECONSTRUCTION_JOB_SELECT + " where j.id = :job_id and p.owner_id = :owner_id"
                ),
                {"job_id": job_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        return _reconstruction_from_row(row) if row is not None else None

    async def get_for_worker(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> WorkerReconstructionJob | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    _RECONSTRUCTION_JOB_SELECT
                    + """
                    where j.id = :job_id and p.owner_id = :owner_id
                    """
                ),
                {"job_id": job_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        reconstruction = _reconstruction_from_row(row)
        return WorkerReconstructionJob(
            reconstruction=reconstruction,
            owner_id=cast(UUID, row["owner_id"]),
            source_artifact=_artifact_from_row(row),
        )

    async def claim_provider_submission(self, *, job_id: UUID, owner_id: UUID) -> bool:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    """
                    update public.jobs j
                    set status = 'running'
                    from public.projects p
                    where j.id = :job_id
                      and j.project_id = p.id
                      and p.owner_id = :owner_id
                      and j.type = 'reconstruction'
                      and j.status = 'queued'
                      and j.provider_job_id is null
                    returning j.id
                    """
                ),
                {"job_id": job_id, "owner_id": owner_id},
            )
        return result.scalar_one_or_none() is not None

    async def persist_provider_job_id(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        provider_job_id: str,
    ) -> None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            await self._session.execute(
                text(
                    """
                    update public.jobs j
                    set provider_job_id = :provider_job_id, status = 'running'
                    from public.projects p
                    where j.id = :job_id
                      and j.project_id = p.id
                      and p.owner_id = :owner_id
                      and j.type = 'reconstruction'
                      and j.provider_job_id is null
                    """
                ),
                {"job_id": job_id, "owner_id": owner_id, "provider_job_id": provider_job_id},
            )

    async def mark_terminal(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            await self._session.execute(
                text(
                    """
                    update public.jobs j
                    set status = :status, error_code = :error_code, error_message = :error_message
                    from public.projects p
                    where j.id = :job_id
                      and j.project_id = p.id
                      and p.owner_id = :owner_id
                      and j.type = 'reconstruction'
                      and j.status in ('queued', 'running')
                    """
                ),
                {
                    "job_id": job_id,
                    "owner_id": owner_id,
                    "status": status,
                    "error_code": error_code,
                    "error_message": error_message,
                },
            )

    async def create_output_artifact(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        artifact_id: UUID,
        blob_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> UUID:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            inserted = await self._session.execute(
                text(
                    """
                    insert into public.artifacts (
                        id, project_id, producer_job_id, kind, blob_name, mime_type, size_bytes,
                        sha256, status, expires_at
                    )
                    select :artifact_id, j.project_id, j.id, 'reconstructed_model', :blob_name,
                           :mime_type, :size_bytes, :sha256, 'ready', null
                    from public.jobs j
                    join public.projects p on p.id = j.project_id
                    where j.id = :job_id and p.owner_id = :owner_id and j.type = 'reconstruction'
                    on conflict do nothing
                    returning id
                    """
                ),
                {
                    "artifact_id": artifact_id,
                    "job_id": job_id,
                    "owner_id": owner_id,
                    "blob_name": blob_name,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                },
            )
            output_id: object | None = inserted.scalar_one_or_none()
            if output_id is None:
                existing = await self._session.execute(
                    text(
                        """
                        select a.id
                        from public.artifacts a
                        join public.jobs j on j.id = a.producer_job_id
                        join public.projects p on p.id = j.project_id
                        where a.producer_job_id = :job_id
                          and a.kind = 'reconstructed_model'
                          and p.owner_id = :owner_id
                        """
                    ),
                    {"job_id": job_id, "owner_id": owner_id},
                )
                output_id = existing.scalar_one()
            return cast(UUID, output_id)

    async def mark_succeeded(self, *, job_id: UUID, owner_id: UUID) -> None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            await self._session.execute(
                text(
                    """
                    update public.jobs j
                    set status = 'succeeded', error_code = null, error_message = null
                    from public.projects p
                    where j.id = :job_id
                      and j.project_id = p.id
                      and p.owner_id = :owner_id
                      and j.type = 'reconstruction'
                      and j.status in ('queued', 'running')
                    """
                ),
                {"job_id": job_id, "owner_id": owner_id},
            )

    async def _get_by_idempotency(
        self,
        *,
        project_id: UUID,
        idempotency_key: str,
    ) -> ReconstructionJob | None:
        result = await self._session.execute(
            text(
                _RECONSTRUCTION_JOB_SELECT
                + " where j.project_id = :project_id and j.idempotency_key = :idempotency_key"
            ),
            {"project_id": project_id, "idempotency_key": idempotency_key},
        )
        row = result.mappings().one_or_none()
        return _reconstruction_from_row(row) if row is not None else None


_RECONSTRUCTION_JOB_SELECT = """
    select j.id, j.project_id, j.type, j.status, j.idempotency_key, j.provider_job_id,
           j.error_code, j.error_message, j.created_at, j.updated_at,
           r.input_artifact_id, p.owner_id,
           source.id as source_id, source.project_id as source_project_id,
           source.kind as source_kind, source.blob_name as source_blob_name,
           source.mime_type as source_mime_type, source.size_bytes as source_size_bytes,
           source.sha256 as source_sha256, source.status as source_status,
           source.expires_at as source_expires_at, source.created_at as source_created_at,
           output.id as output_artifact_id
    from public.jobs j
    join public.projects p on p.id = j.project_id
    join public.reconstruction_runs r on r.job_id = j.id
    join public.artifacts source on source.id = r.input_artifact_id
    left join public.artifacts output
      on output.producer_job_id = j.id and output.kind = 'reconstructed_model'
"""


def _job_from_row(row: RowMapping) -> Job:
    return Job(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        type=JobType(cast(str, row["type"])),
        status=JobStatus(cast(str, row["status"])),
        idempotency_key=cast(str, row["idempotency_key"]),
        provider_job_id=cast(str | None, row["provider_job_id"]),
        error_code=cast(str | None, row["error_code"]),
        error_message=cast(str | None, row["error_message"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _reconstruction_from_row(row: RowMapping) -> ReconstructionJob:
    return ReconstructionJob(
        job=_job_from_row(row),
        source_artifact_id=cast(UUID, row["input_artifact_id"]),
        output_artifact_id=cast(UUID | None, row["output_artifact_id"]),
    )


def _artifact_from_row(row: RowMapping) -> Artifact:
    return Artifact(
        id=cast(UUID, row["source_id"]),
        project_id=cast(UUID, row["source_project_id"]),
        kind=cast(str, row["source_kind"]),
        blob_name=cast(str, row["source_blob_name"]),
        mime_type=cast(str, row["source_mime_type"]),
        size_bytes=cast(int, row["source_size_bytes"]),
        sha256=cast(str, row["source_sha256"]),
        status=ArtifactStatus(cast(str, row["source_status"])),
        expires_at=cast(datetime | None, row["source_expires_at"]),
        created_at=cast(datetime, row["source_created_at"]),
    )
