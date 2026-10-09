from typing import Protocol
from uuid import UUID

from app.domain.jobs import JobStatusRecord


class JobRepository(Protocol):
    async def get_for_owner(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
    ) -> JobStatusRecord | None: ...
