from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import AuthenticatedUser, get_current_user

router = APIRouter(tags=["authentication"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


class ProfileResponse(BaseModel):
    id: str
    email: str | None = None
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    avatar_url: str | None = Field(default=None, serialization_alias="avatarUrl")


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(current_user: CurrentUser) -> ProfileResponse:
    return ProfileResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )
