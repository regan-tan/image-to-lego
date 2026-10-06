import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.errors import ApplicationError
from app.domain.artifacts import Artifact, ArtifactStatus
from app.providers.blob_storage import BlobStorage, BlobStorageError
from app.repositories.uploads import PendingUploadRejection, UploadRepository

ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILENAME_LENGTH = 255


@dataclass(frozen=True, slots=True)
class UploadInitiation:
    artifact: Artifact
    upload_url: str = field(repr=False)
    upload_url_expires_at: datetime
    required_headers: dict[str, str]


class UploadService:
    def __init__(
        self,
        *,
        repository: UploadRepository,
        blob_storage: BlobStorage,
        max_image_size_bytes: int,
        quota_limit: int,
        quota_window: timedelta,
        pending_lifetime: timedelta,
        sas_lifetime: timedelta,
    ) -> None:
        self._repository = repository
        self._blob_storage = blob_storage
        self._max_image_size_bytes = max_image_size_bytes
        self._quota_limit = quota_limit
        self._quota_window = quota_window
        self._pending_lifetime = pending_lifetime
        self._sas_lifetime = sas_lifetime

    async def initiate(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> UploadInitiation:
        safe_file_name = _normalize_file_name(file_name)
        normalized_mime_type = mime_type.lower()
        if normalized_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise ApplicationError(
                code="unsupported_image_type",
                message="Only JPEG, PNG, and WebP images are supported.",
            )
        if size_bytes <= 0:
            raise ApplicationError(
                code="invalid_image_size",
                message="Image size must be greater than zero.",
            )
        if size_bytes > self._max_image_size_bytes:
            raise ApplicationError(
                code="image_too_large",
                message="The selected image exceeds the maximum allowed size.",
            )
        if not SHA256_PATTERN.fullmatch(sha256):
            raise ApplicationError(
                code="invalid_sha256",
                message="SHA-256 must contain exactly 64 hexadecimal characters.",
            )

        now = datetime.now(UTC)
        artifact_id = uuid4()
        blob_name = f"projects/{project_id}/uploads/{artifact_id}/{safe_file_name}"
        pending = await self._repository.create_pending(
            artifact_id=artifact_id,
            owner_id=owner_id,
            project_id=project_id,
            blob_name=blob_name,
            mime_type=normalized_mime_type,
            size_bytes=size_bytes,
            sha256=sha256.lower(),
            expires_at=now + self._pending_lifetime,
            quota_started_at=now - self._quota_window,
            quota_window=self._quota_window,
            quota_limit=self._quota_limit,
        )
        if pending.rejection is PendingUploadRejection.PROJECT_NOT_FOUND:
            raise ApplicationError(
                code="project_not_found",
                message="The project does not exist.",
            )
        if pending.rejection is PendingUploadRejection.QUOTA_EXCEEDED:
            retry_after_seconds = 1
            if pending.retry_at is not None:
                retry_after_seconds = max(1, math.ceil((pending.retry_at - now).total_seconds()))
            raise ApplicationError(
                code="upload_quota_exceeded",
                message="The rolling upload limit has been reached.",
                retry_after_seconds=retry_after_seconds,
            )
        if pending.artifact is None:
            raise RuntimeError("Upload repository returned no artifact or rejection.")

        upload_url_expires_at = now + self._sas_lifetime
        try:
            upload_url = await self._blob_storage.create_upload_url(
                blob_name=pending.artifact.blob_name,
                expires_at=upload_url_expires_at,
            )
        except BlobStorageError as error:
            raise ApplicationError(
                code="blob_storage_unavailable",
                message="Image storage is temporarily unavailable.",
            ) from error

        return UploadInitiation(
            artifact=pending.artifact,
            upload_url=upload_url,
            upload_url_expires_at=upload_url_expires_at,
            required_headers={
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": normalized_mime_type,
                "x-ms-meta-sha256": sha256.lower(),
            },
        )

    async def complete(self, *, owner_id: UUID, artifact_id: UUID) -> Artifact:
        artifact = await self._repository.get_for_owner(
            artifact_id=artifact_id,
            owner_id=owner_id,
        )
        if artifact is None or artifact.kind != "source_image":
            raise ApplicationError(code="upload_not_found", message="The upload does not exist.")
        if artifact.status is ArtifactStatus.READY:
            return artifact

        now = datetime.now(UTC)
        if artifact.expires_at is None or artifact.expires_at <= now:
            raise ApplicationError(
                code="upload_expired",
                message="The upload has expired. Start a new upload.",
            )

        try:
            properties = await self._blob_storage.get_properties(blob_name=artifact.blob_name)
        except BlobStorageError as error:
            raise ApplicationError(
                code="blob_storage_unavailable",
                message="Image storage is temporarily unavailable.",
            ) from error
        if properties is None:
            raise ApplicationError(
                code="uploaded_blob_missing",
                message="The uploaded image was not found.",
            )
        if (
            properties.size_bytes != artifact.size_bytes
            or properties.content_type != artifact.mime_type
            or properties.sha256 != artifact.sha256
        ):
            raise ApplicationError(
                code="uploaded_blob_mismatch",
                message="The uploaded image metadata does not match the pending upload.",
            )

        ready_artifact = await self._repository.mark_ready(
            artifact_id=artifact_id,
            owner_id=owner_id,
        )
        if ready_artifact is None:
            raise ApplicationError(code="upload_not_found", message="The upload does not exist.")
        return ready_artifact


def _normalize_file_name(file_name: str) -> str:
    normalized = unicodedata.normalize("NFKC", file_name).strip()
    if (
        not normalized
        or len(normalized) > MAX_FILENAME_LENGTH
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or any(unicodedata.category(character).startswith("C") for character in normalized)
    ):
        raise ApplicationError(
            code="invalid_file_name",
            message="The image filename is invalid.",
        )

    safe_file_name = UNSAFE_FILENAME_CHARACTERS.sub("_", normalized).strip("._")
    if not safe_file_name:
        raise ApplicationError(
            code="invalid_file_name",
            message="The image filename is invalid.",
        )
    return safe_file_name
