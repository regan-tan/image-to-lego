from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_database_owner
from app.domain.projects import Project


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

    async def list_for_owner(self, *, owner_id: UUID) -> list[Project]:
        async with self._session.begin():
            await set_database_owner(self._session, owner_id)
            result = await self._session.execute(
                text(
                    """
                    select id, owner_id, name, created_at, updated_at
                    from public.projects
                    where owner_id = :owner_id
                    order by updated_at desc, id desc
                    """
                ),
                {"owner_id": owner_id},
            )
        return [_project_from_row(row) for row in result.mappings()]


def _project_from_row(row: RowMapping) -> Project:
    return Project(
        id=cast(UUID, row["id"]),
        owner_id=cast(UUID, row["owner_id"]),
        name=cast(str, row["name"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )
