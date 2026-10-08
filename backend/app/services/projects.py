from uuid import UUID

from app.core.errors import ApplicationError
from app.domain.projects import Project, ProjectOverview
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

    async def list_overviews_for_owner(self, *, owner_id: UUID) -> list[ProjectOverview]:
        return await self._repository.list_overviews_for_owner(owner_id=owner_id)

    async def get_overview_for_owner(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
    ) -> ProjectOverview | None:
        return await self._repository.get_overview_for_owner(
            project_id=project_id,
            owner_id=owner_id,
        )
