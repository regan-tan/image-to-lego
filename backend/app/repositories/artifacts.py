from typing import Protocol
from uuid import UUID

from app.domain.artifacts import Artifact


class ArtifactRepository(Protocol):
    async def get_for_owner(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None: ...
