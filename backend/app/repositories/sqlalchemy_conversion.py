from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversion import ALGORITHM_VERSION
from app.core.database import set_database_owner
from app.domain.artifacts import Artifact, ArtifactStatus
from app.domain.jobs import ConversionJob, Job, JobStatus, JobType, WorkerConversionJob
from app.repositories.conversion import (
    ConversionInitiation,
    ConversionInitiationRejection,
)


class SqlAlchemyConversionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        source_artifact_id: UUID,
        target_parts: int,
        up_axis: str,
        idempotency_key: str,
    ) -> ConversionInitiation:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            project = await self._session.execute(
                text(
                    "select id from public.projects where id = :project_id and owner_id = :owner_id"
                ),
                {"project_id": project_id, "owner_id": owner_id},
            )
            if project.scalar_one_or_none() is None:
                return ConversionInitiation(rejection=ConversionInitiationRejection.NOT_FOUND)

            source_result = await self._session.execute(
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
            source_row = source_result.mappings().one_or_none()
            if source_row is None:
                return ConversionInitiation(rejection=ConversionInitiationRejection.NOT_FOUND)
            source = _artifact_from_row(source_row)
            if source.kind != "reconstructed_model":
                return ConversionInitiation(
                    rejection=ConversionInitiationRejection.WRONG_ARTIFACT_KIND
                )
            if source.status is not ArtifactStatus.READY:
                return ConversionInitiation(
                    rejection=ConversionInitiationRejection.SOURCE_NOT_READY
                )

            existing = await self._get_by_idempotency(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                if (
                    existing.source_artifact_id != source_artifact_id
                    or existing.target_parts != target_parts
                    or existing.up_axis != up_axis
                ):
                    return ConversionInitiation(
                        rejection=ConversionInitiationRejection.IDEMPOTENCY_CONFLICT
                    )
                return ConversionInitiation(conversion=existing)

            job_id = uuid4()
            inserted = await self._session.execute(
                text(
                    """
                    insert into public.jobs (id, project_id, type, status, idempotency_key)
                    values (:job_id, :project_id, 'conversion', 'queued', :idempotency_key)
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
                    raise RuntimeError("Could not read the conflicting conversion job.")
                if (
                    existing.source_artifact_id != source_artifact_id
                    or existing.target_parts != target_parts
                    or existing.up_axis != up_axis
                ):
                    return ConversionInitiation(
                        rejection=ConversionInitiationRejection.IDEMPOTENCY_CONFLICT
                    )
                return ConversionInitiation(conversion=existing)

            await self._session.execute(
                text(
                    """
                    insert into public.conversion_runs (
                        job_id, source_artifact_id, target_parts, up_axis, algorithm_version
                    )
                    values (
                        :job_id, :source_artifact_id, :target_parts, :up_axis, :algorithm_version
                    )
                    """
                ),
                {
                    "job_id": job_id,
                    "source_artifact_id": source_artifact_id,
                    "target_parts": target_parts,
                    "up_axis": up_axis,
                    "algorithm_version": ALGORITHM_VERSION,
                },
            )
            return ConversionInitiation(
                conversion=ConversionJob(
                    job=_job_from_row(row),
                    source_artifact_id=source_artifact_id,
                    target_parts=target_parts,
                    up_axis=up_axis,
                    output_artifact_id=None,
                ),
                created=True,
            )

    async def mark_queue_publish_failed(self, *, job_id: UUID, owner_id: UUID) -> None:
        await self.mark_failed(
            job_id=job_id,
            owner_id=owner_id,
            error_code="conversion_queue_unavailable",
            error_message="Conversion could not be queued. Please start it again.",
        )

    async def get_for_worker(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> WorkerConversionJob | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(_CONVERSION_JOB_SELECT + " where j.id = :job_id and p.owner_id = :owner_id"),
                {"job_id": job_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return WorkerConversionJob(
            conversion=_conversion_from_row(row),
            owner_id=cast(UUID, row["owner_id"]),
            source_artifact=_artifact_from_row(row),
        )

    async def claim(self, *, job_id: UUID, owner_id: UUID) -> bool:
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
                      and j.type = 'conversion'
                      and j.status = 'queued'
                    returning j.id
                    """
                ),
                {"job_id": job_id, "owner_id": owner_id},
            )
        return result.scalar_one_or_none() is not None

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            await self._session.execute(
                text(
                    """
                    update public.jobs j
                    set status = 'failed', error_code = :error_code, error_message = :error_message
                    from public.projects p
                    where j.id = :job_id
                      and j.project_id = p.id
                      and p.owner_id = :owner_id
                      and j.type = 'conversion'
                      and j.status in ('queued', 'running')
                    """
                ),
                {
                    "job_id": job_id,
                    "owner_id": owner_id,
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
                    select :artifact_id, j.project_id, j.id, 'lego_model', :blob_name,
                           :mime_type, :size_bytes, :sha256, 'ready', null
                    from public.jobs j
                    join public.projects p on p.id = j.project_id
                    where j.id = :job_id and p.owner_id = :owner_id and j.type = 'conversion'
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
                          and a.kind = 'lego_model'
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
                      and j.type = 'conversion'
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
    ) -> ConversionJob | None:
        result = await self._session.execute(
            text(
                _CONVERSION_JOB_SELECT
                + " where j.project_id = :project_id and j.idempotency_key = :idempotency_key"
            ),
            {"project_id": project_id, "idempotency_key": idempotency_key},
        )
        row = result.mappings().one_or_none()
        return _conversion_from_row(row) if row is not None else None


_CONVERSION_JOB_SELECT = """
    select j.id, j.project_id, j.type, j.status, j.idempotency_key, j.provider_job_id,
           j.error_code, j.error_message, j.created_at, j.updated_at,
           r.source_artifact_id, r.target_parts, r.up_axis, p.owner_id,
           source.id as source_id, source.project_id as source_project_id,
           source.kind as source_kind, source.blob_name as source_blob_name,
           source.mime_type as source_mime_type, source.size_bytes as source_size_bytes,
           source.sha256 as source_sha256, source.status as source_status,
           source.expires_at as source_expires_at, source.created_at as source_created_at,
           output.id as output_artifact_id
    from public.jobs j
    join public.projects p on p.id = j.project_id
    join public.conversion_runs r on r.job_id = j.id
    join public.artifacts source on source.id = r.source_artifact_id
    left join public.artifacts output
      on output.producer_job_id = j.id and output.kind = 'lego_model'
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


def _conversion_from_row(row: RowMapping) -> ConversionJob:
    return ConversionJob(
        job=_job_from_row(row),
        source_artifact_id=cast(UUID, row["source_artifact_id"]),
        target_parts=cast(int, row["target_parts"]),
        up_axis=cast(str, row["up_axis"]),
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
