from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = cast(
        async_sessionmaker[AsyncSession] | None,
        getattr(request.app.state, "session_factory", None),
    )
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database access is not configured.",
        )

    async with session_factory() as session:
        yield session


DatabaseSession = Annotated[AsyncSession, Depends(get_database_session)]


async def set_database_owner(session: AsyncSession, owner_id: UUID) -> None:
    """Set verified request identity for RLS for the current transaction only."""
    await session.execute(
        text("select set_config('app.current_user_id', :owner_id, true)"),
        {"owner_id": str(owner_id)},
    )
