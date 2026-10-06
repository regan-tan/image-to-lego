from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_database_owner
from app.domain.artifacts import Artifact, ArtifactStatus
from app.repositories.uploads import PendingUploadRejection, PendingUploadResult


class SqlAlchemyUploadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(
        self,
        *,
        artifact_id: UUID,
        owner_id: UUID,
        project_id: UUID,
        blob_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        expires_at: datetime,
        quota_started_at: datetime,
        quota_window: timedelta,
        quota_limit: int,
    ) -> PendingUploadResult:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            # Serialize initiations per owner so parallel requests cannot exceed the quota.
            await self._session.execute(
                text("select pg_advisory_xact_lock(hashtextextended(cast(:owner_id as text), 0))"),
                {"owner_id": str(owner_id)},
            )
            project = await self._session.execute(
                text(
                    """
                    select id
                    from public.projects
                    where id = :project_id and owner_id = :owner_id
                    """
                ),
                {"project_id": project_id, "owner_id": owner_id},
            )
            if project.scalar_one_or_none() is None:
                return PendingUploadResult(rejection=PendingUploadRejection.PROJECT_NOT_FOUND)

            quota = await self._session.execute(
                text(
                    """
                    select count(*) as upload_count, min(a.created_at) as oldest_created_at
                    from public.artifacts a
                    join public.projects p on p.id = a.project_id
                    where p.owner_id = :owner_id
                      and a.kind = 'source_image'
                      and a.created_at >= :quota_started_at
                    """
                ),
                {"owner_id": owner_id, "quota_started_at": quota_started_at},
            )
            quota_row = quota.mappings().one()
            if cast(int, quota_row["upload_count"]) >= quota_limit:
                oldest_created_at = cast(datetime, quota_row["oldest_created_at"])
                return PendingUploadResult(
                    rejection=PendingUploadRejection.QUOTA_EXCEEDED,
                    retry_at=oldest_created_at + quota_window,
                )

            inserted = await self._session.execute(
                text(
                    """
                    insert into public.artifacts (
                        id, project_id, kind, blob_name, mime_type, size_bytes,
                        sha256, status, expires_at
                    )
                    values (
                        :artifact_id, :project_id, 'source_image', :blob_name, :mime_type,
                        :size_bytes, :sha256, 'pending', :expires_at
                    )
                    returning id, project_id, kind, blob_name, mime_type, size_bytes,
                              sha256, status, expires_at, created_at
                    """
                ),
                {
                    "artifact_id": artifact_id,
                    "project_id": project_id,
                    "blob_name": blob_name,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                    "expires_at": expires_at,
                },
            )
            return PendingUploadResult(artifact=_artifact_from_row(inserted.mappings().one()))

    async def get_for_owner(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    """
                    select a.id, a.project_id, a.kind, a.blob_name, a.mime_type, a.size_bytes,
                           a.sha256, a.status, a.expires_at, a.created_at
                    from public.artifacts a
                    join public.projects p on p.id = a.project_id
                    where a.id = :artifact_id and p.owner_id = :owner_id
                    """
                ),
                {"artifact_id": artifact_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        return _artifact_from_row(row) if row is not None else None

    async def mark_ready(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    """
                    update public.artifacts a
                    set status = 'ready', expires_at = null
                    from public.projects p
                    where a.id = :artifact_id
                      and a.project_id = p.id
                      and p.owner_id = :owner_id
                      and a.status = 'pending'
                    returning a.id, a.project_id, a.kind, a.blob_name, a.mime_type,
                              a.size_bytes, a.sha256, a.status, a.expires_at, a.created_at
                    """
                ),
                {"artifact_id": artifact_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        if row is not None:
            return _artifact_from_row(row)
        return await self.get_for_owner(artifact_id=artifact_id, owner_id=owner_id)


def _artifact_from_row(row: RowMapping) -> Artifact:
    return Artifact(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        kind=cast(str, row["kind"]),
        blob_name=cast(str, row["blob_name"]),
        mime_type=cast(str, row["mime_type"]),
        size_bytes=cast(int, row["size_bytes"]),
        sha256=cast(str, row["sha256"]),
        status=ArtifactStatus(cast(str, row["status"])),
        expires_at=cast(datetime | None, row["expires_at"]),
        created_at=cast(datetime, row["created_at"]),
    )
