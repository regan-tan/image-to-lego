from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.artifacts import get_artifact_repository
from app.api.v1.uploads import get_blob_storage
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings
from app.domain.artifacts import Artifact, ArtifactStatus
from app.main import create_app
from app.providers.blob_storage import BlobStorageError

OWNER_ID = UUID("0c3d60a8-5117-44e5-821b-abc1c0c8f3d0")
OTHER_OWNER_ID = UUID("6e43e80d-9276-4d37-af4f-12f7f85d4f50")
READ_URL_LIFETIME_MINUTES = 7


def make_artifact(
    *,
    kind: str = "reconstructed_model",
    mime_type: str = "model/gltf-binary",
    status: ArtifactStatus = ArtifactStatus.READY,
) -> Artifact:
    return Artifact(
        id=uuid4(),
        project_id=uuid4(),
        kind=kind,
        blob_name=f"projects/p/{kind}/file",
        mime_type=mime_type,
        size_bytes=1_024,
        sha256="a" * 64,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(hours=1)
        if status == ArtifactStatus.PENDING
        else None,
        created_at=datetime.now(UTC),
    )


class FakeArtifactRepository:
    def __init__(self) -> None:
        self.artifacts: dict[UUID, tuple[UUID, Artifact]] = {}

    def add(self, artifact: Artifact, owner_id: UUID = OWNER_ID) -> Artifact:
        self.artifacts[artifact.id] = (owner_id, artifact)
        return artifact

    async def get_for_owner(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None:
        stored = self.artifacts.get(artifact_id)
        return stored[1] if stored is not None and stored[0] == owner_id else None


class FakeBlobStorage:
    def __init__(self) -> None:
        self.read_requests: list[dict[str, object]] = []
        self.fail = False

    async def create_read_url(
        self,
        *,
        blob_name: str,
        expires_at: datetime,
        download_file_name: str | None = None,
    ) -> str:
        if self.fail:
            raise BlobStorageError("Azure is unavailable.")
        self.read_requests.append(
            {
                "blob_name": blob_name,
                "expires_at": expires_at,
                "download_file_name": download_file_name,
            }
        )
        return f"https://storage.example.test/container/{blob_name}?sp=r&sig=secret"


@pytest.fixture
def api_context() -> tuple[httpx.AsyncClient, FakeArtifactRepository, FakeBlobStorage]:
    repository = FakeArtifactRepository()
    blob_storage = FakeBlobStorage()
    app = create_app(Settings(artifact_read_url_lifetime_minutes=READ_URL_LIFETIME_MINUTES))

    async def current_user() -> AuthenticatedUser:
        return AuthenticatedUser(
            id=str(OWNER_ID),
            email="builder@example.com",
            display_name=None,
            avatar_url=None,
        )

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_artifact_repository] = lambda: repository
    app.dependency_overrides[get_blob_storage] = lambda: blob_storage
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, repository, blob_storage


ApiContext = tuple[httpx.AsyncClient, FakeArtifactRepository, FakeBlobStorage]


@pytest.mark.asyncio
async def test_read_url_is_short_lived_for_one_blob_and_never_cached(
    api_context: ApiContext,
) -> None:
    client, repository, blob_storage = api_context
    model = repository.add(make_artifact())
    before = datetime.now(UTC)

    response = await client.get(f"/api/v1/artifacts/{model.id}/read-url")
    await client.aclose()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["url"].startswith(
        f"https://storage.example.test/container/{model.blob_name}?"
    )
    expires_at = datetime.fromisoformat(response.json()["expiresAt"])
    assert before + timedelta(minutes=READ_URL_LIFETIME_MINUTES) <= expires_at
    assert expires_at <= datetime.now(UTC) + timedelta(minutes=READ_URL_LIFETIME_MINUTES)
    assert blob_storage.read_requests == [
        {"blob_name": model.blob_name, "expires_at": expires_at, "download_file_name": None}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "mime_type", "expected_file_name"),
    [
        ("reconstructed_model", "model/gltf-binary", "model.glb"),
        ("source_image", "image/jpeg", "photo.jpg"),
        ("source_image", "image/webp", "photo.webp"),
    ],
)
async def test_download_links_ask_the_browser_to_save_with_a_clear_file_name(
    api_context: ApiContext,
    kind: str,
    mime_type: str,
    expected_file_name: str,
) -> None:
    client, repository, blob_storage = api_context
    artifact = repository.add(make_artifact(kind=kind, mime_type=mime_type))

    response = await client.get(f"/api/v1/artifacts/{artifact.id}/read-url?download=true")
    await client.aclose()

    assert response.status_code == 200
    assert blob_storage.read_requests[0]["download_file_name"] == expected_file_name


@pytest.mark.asyncio
async def test_read_url_does_not_reveal_missing_or_other_users_files(
    api_context: ApiContext,
) -> None:
    client, repository, blob_storage = api_context
    other_users_model = repository.add(make_artifact(), owner_id=OTHER_OWNER_ID)

    missing = await client.get(f"/api/v1/artifacts/{uuid4()}/read-url")
    not_owned = await client.get(f"/api/v1/artifacts/{other_users_model.id}/read-url")
    await client.aclose()

    assert missing.status_code == 404
    assert not_owned.status_code == 404
    assert missing.json() == not_owned.json()
    assert blob_storage.read_requests == []


@pytest.mark.asyncio
async def test_read_url_is_only_issued_for_photos_and_models(api_context: ApiContext) -> None:
    client, repository, blob_storage = api_context
    other_kind = repository.add(
        make_artifact(kind="lego_instructions", mime_type="application/pdf")
    )

    response = await client.get(f"/api/v1/artifacts/{other_kind.id}/read-url")
    await client.aclose()

    assert response.status_code == 404
    assert blob_storage.read_requests == []


@pytest.mark.asyncio
async def test_read_url_is_refused_while_an_upload_is_still_pending(
    api_context: ApiContext,
) -> None:
    client, repository, blob_storage = api_context
    pending_photo = repository.add(
        make_artifact(kind="source_image", mime_type="image/png", status=ArtifactStatus.PENDING)
    )

    response = await client.get(f"/api/v1/artifacts/{pending_photo.id}/read-url")
    await client.aclose()

    assert response.status_code == 409
    assert blob_storage.read_requests == []


@pytest.mark.asyncio
async def test_storage_failures_become_a_safe_service_unavailable_error(
    api_context: ApiContext,
) -> None:
    client, repository, blob_storage = api_context
    model = repository.add(make_artifact())
    blob_storage.fail = True

    response = await client.get(f"/api/v1/artifacts/{model.id}/read-url")
    await client.aclose()

    assert response.status_code == 503
    assert response.json() == {"detail": "File access is temporarily unavailable."}


@pytest.mark.asyncio
async def test_read_url_requires_authentication() -> None:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/artifacts/{uuid4()}/read-url")

    assert response.status_code == 401
