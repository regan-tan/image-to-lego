from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.core.auth import AuthenticatedUser, get_current_user, unauthorized

CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def get_current_owner_id(current_user: CurrentUser) -> UUID:
    try:
        return UUID(current_user.id)
    except ValueError as error:
        raise unauthorized() from error


CurrentOwnerId = Annotated[UUID, Depends(get_current_owner_id)]
