from typing import Protocol
from uuid import UUID

from app.domain.projects import Project


class ProjectRepository(Protocol):
    async def create(self, *, owner_id: UUID, name: str) -> Project: ...

    async def get_for_owner(self, *, project_id: UUID, owner_id: UUID) -> Project | None: ...

    async def list_for_owner(self, *, owner_id: UUID) -> list[Project]: ...

