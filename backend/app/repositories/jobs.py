from typing import Protocol
from uuid import UUID

from app.domain.jobs import Job, JobStatus, JobType


class JobRepository(Protocol):
    async def create(
        self,
        *,
        project_id: UUID,
        job_type: JobType,
        idempotency_key: str,
    ) -> Job: ...

    async def get(self, *, job_id: UUID) -> Job | None: ...

    async def set_status(self, *, job_id: UUID, status: JobStatus) -> Job: ...
