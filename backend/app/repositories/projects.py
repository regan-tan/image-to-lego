from typing import Protocol
from uuid import UUID

from app.domain.projects import Project, ProjectOverview


class ProjectRepository(Protocol):
    async def create(self, *, owner_id: UUID, name: str) -> Project: ...

    async def get_for_owner(self, *, project_id: UUID, owner_id: UUID) -> Project | None: ...

    async def get_overview_for_owner(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
    ) -> ProjectOverview | None: ...

    async def list_overviews_for_owner(self, *, owner_id: UUID) -> list[ProjectOverview]: ...
