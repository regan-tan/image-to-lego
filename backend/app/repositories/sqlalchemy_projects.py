from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_database_owner
from app.domain.jobs import JobStatus
from app.domain.projects import (
    Project,
    ProjectOverview,
    ProjectReconstruction,
    ProjectSourceImage,
)

# One row per project with its latest ready source image and the latest reconstruction started
# from that image. LATERAL joins keep this a single query for the whole list (no N+1 queries) and
# use the existing (project_id, kind, created_at) and (project_id, created_at) indexes.
_PROJECT_OVERVIEW_SELECT = """
    select
        p.id, p.owner_id, p.name, p.created_at, p.updated_at,
        source_image.id as source_image_id,
        source_image.mime_type as source_image_mime_type,
        source_image.size_bytes as source_image_size_bytes,
        source_image.created_at as source_image_created_at,
        reconstruction.id as reconstruction_job_id,
        reconstruction.status as reconstruction_status,
        reconstruction.output_artifact_id as reconstruction_output_artifact_id,
        reconstruction.error_code as reconstruction_error_code,
        reconstruction.error_message as reconstruction_error_message,
        reconstruction.created_at as reconstruction_created_at,
        reconstruction.updated_at as reconstruction_updated_at
    from public.projects p
    left join lateral (
        select a.id, a.mime_type, a.size_bytes, a.created_at
        from public.artifacts a
        where a.project_id = p.id
          and a.kind = 'source_image'
          and a.status = 'ready'
        order by a.created_at desc, a.id desc
        limit 1
    ) source_image on true
    left join lateral (
        select
            j.id, j.status, j.error_code, j.error_message, j.created_at, j.updated_at,
            output.id as output_artifact_id
        from public.jobs j
        join public.reconstruction_runs r on r.job_id = j.id
        left join public.artifacts output
          on output.producer_job_id = j.id and output.kind = 'reconstructed_model'
        where j.project_id = p.id
          and j.type = 'reconstruction'
          and r.input_artifact_id = source_image.id
        order by j.created_at desc, j.id desc
        limit 1
    ) reconstruction on true
"""


class SqlAlchemyProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, owner_id: UUID, name: str) -> Project:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    """
                    insert into public.projects (owner_id, name)
                    values (:owner_id, :name)
                    returning id, owner_id, name, created_at, updated_at
                    """
                ),
                {"owner_id": owner_id, "name": name},
            )
        return _project_from_row(result.mappings().one())

    async def get_for_owner(self, *, project_id: UUID, owner_id: UUID) -> Project | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    """
                    select id, owner_id, name, created_at, updated_at
                    from public.projects
                    where id = :project_id and owner_id = :owner_id
                    """
                ),
                {"project_id": project_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        return _project_from_row(row) if row is not None else None

    async def get_overview_for_owner(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
    ) -> ProjectOverview | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    _PROJECT_OVERVIEW_SELECT
                    + " where p.id = :project_id and p.owner_id = :owner_id"
                ),
                {"project_id": project_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        return _overview_from_row(row) if row is not None else None

    async def list_overviews_for_owner(self, *, owner_id: UUID) -> list[ProjectOverview]:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    _PROJECT_OVERVIEW_SELECT
                    + " where p.owner_id = :owner_id order by p.updated_at desc, p.id desc"
                ),
                {"owner_id": owner_id},
            )
        return [_overview_from_row(row) for row in result.mappings()]


def _project_from_row(row: RowMapping) -> Project:
    return Project(
        id=cast(UUID, row["id"]),
        owner_id=cast(UUID, row["owner_id"]),
        name=cast(str, row["name"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _overview_from_row(row: RowMapping) -> ProjectOverview:
    source_image = None
    if row["source_image_id"] is not None:
        source_image = ProjectSourceImage(
            artifact_id=cast(UUID, row["source_image_id"]),
            mime_type=cast(str, row["source_image_mime_type"]),
            size_bytes=cast(int, row["source_image_size_bytes"]),
            created_at=cast(datetime, row["source_image_created_at"]),
        )
    reconstruction = None
    if row["reconstruction_job_id"] is not None:
        reconstruction = ProjectReconstruction(
            job_id=cast(UUID, row["reconstruction_job_id"]),
            status=JobStatus(cast(str, row["reconstruction_status"])),
            output_artifact_id=cast(UUID | None, row["reconstruction_output_artifact_id"]),
            error_code=cast(str | None, row["reconstruction_error_code"]),
            error_message=cast(str | None, row["reconstruction_error_message"]),
            created_at=cast(datetime, row["reconstruction_created_at"]),
            updated_at=cast(datetime, row["reconstruction_updated_at"]),
        )
    return ProjectOverview(
        project=_project_from_row(row),
        source_image=source_image,
        reconstruction=reconstruction,
    )
