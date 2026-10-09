from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_database_owner
from app.domain.jobs import Job, JobStatus, JobStatusRecord, JobType


class SqlAlchemyJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_owner(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> JobStatusRecord | None:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    """
                    select j.id, j.project_id, j.type, j.status, j.idempotency_key,
                           j.provider_job_id, j.error_code, j.error_message,
                           j.created_at, j.updated_at, output.id as output_artifact_id
                    from public.jobs j
                    join public.projects p on p.id = j.project_id
                    left join public.artifacts output
                      on output.producer_job_id = j.id
                     and (
                        (j.type = 'reconstruction' and output.kind = 'reconstructed_model')
                        or (j.type = 'conversion' and output.kind = 'lego_model')
                     )
                    where j.id = :job_id and p.owner_id = :owner_id
                    """
                ),
                {"job_id": job_id, "owner_id": owner_id},
            )
        row = result.mappings().one_or_none()
        return _job_status_from_row(row) if row is not None else None


def _job_status_from_row(row: RowMapping) -> JobStatusRecord:
    return JobStatusRecord(
        job=Job(
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
        ),
        output_artifact_id=cast(UUID | None, row["output_artifact_id"]),
    )
