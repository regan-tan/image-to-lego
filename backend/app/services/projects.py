from uuid import UUID

from app.core.errors import ApplicationError
from app.domain.projects import Project
from app.repositories.projects import ProjectRepository


class ProjectService:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def create(self, *, owner_id: UUID, name: str) -> Project:
        normalized_name = name.strip()
        if not normalized_name:
            raise ApplicationError(
                code="invalid_project_name",
                message="Project name must not be empty.",
            )
        return await self._repository.create(owner_id=owner_id, name=normalized_name)

    async def list_for_owner(self, *, owner_id: UUID) -> list[Project]:
        return await self._repository.list_for_owner(owner_id=owner_id)

