from typing import Protocol
from uuid import UUID

from app.domain.projects import Project, ProjectDeletion, ProjectOverview


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

    async def delete_for_owner(self, *, project_id: UUID, owner_id: UUID) -> ProjectDeletion: ...


class ProjectExistenceRepository(Protocol):
    """Cross-owner existence check used only by the Blob sweep; it reveals no project data."""

    async def existing_project_ids(self, *, candidate_ids: list[UUID]) -> set[UUID]: ...
