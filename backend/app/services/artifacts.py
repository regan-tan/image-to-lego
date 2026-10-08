from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.errors import ApplicationError
from app.domain.artifacts import Artifact, ArtifactStatus
from app.providers.blob_storage import BlobStorage, BlobStorageError
from app.repositories.artifacts import ArtifactRepository

# Only files the browser legitimately shows or downloads; any other kind is treated as missing.
DOWNLOAD_FILE_NAMES_BY_KIND = {
    "source_image": "photo",
    "reconstructed_model": "model",
}
FILE_EXTENSIONS_BY_MIME_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "model/gltf-binary": "glb",
}


@dataclass(frozen=True, slots=True)
class ArtifactReadUrl:
    url: str = field(repr=False)
    expires_at: datetime


class ArtifactAccessService:
    """Issues short-lived, read-only links so the browser loads private files straight from Blob."""

    def __init__(
        self,
        *,
        repository: ArtifactRepository,
        blob_storage: BlobStorage,
        read_url_lifetime: timedelta,
    ) -> None:
        self._repository = repository
        self._blob_storage = blob_storage
        self._read_url_lifetime = read_url_lifetime

    async def create_read_url(
        self,
        *,
        owner_id: UUID,
        artifact_id: UUID,
        download: bool,
    ) -> ArtifactReadUrl:
        artifact = await self._repository.get_for_owner(artifact_id=artifact_id, owner_id=owner_id)
        if artifact is None or artifact.kind not in DOWNLOAD_FILE_NAMES_BY_KIND:
            raise ApplicationError(code="artifact_not_found", message="The file does not exist.")
        if artifact.status != ArtifactStatus.READY:
            raise ApplicationError(code="artifact_not_ready", message="The file is not ready yet.")

        expires_at = datetime.now(UTC) + self._read_url_lifetime
        try:
            url = await self._blob_storage.create_read_url(
                blob_name=artifact.blob_name,
                expires_at=expires_at,
                download_file_name=_download_file_name(artifact) if download else None,
            )
        except BlobStorageError as error:
            raise ApplicationError(
                code="storage_unavailable",
                message="File access is temporarily unavailable.",
            ) from error
        return ArtifactReadUrl(url=url, expires_at=expires_at)


def _download_file_name(artifact: Artifact) -> str:
    base_name = DOWNLOAD_FILE_NAMES_BY_KIND[artifact.kind]
    extension = FILE_EXTENSIONS_BY_MIME_TYPE.get(artifact.mime_type)
    return f"{base_name}.{extension}" if extension else base_name
