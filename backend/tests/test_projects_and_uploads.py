from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.projects import get_project_repository
from app.api.v1.uploads import get_blob_storage, get_upload_repository
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings
from app.domain.artifacts import Artifact, ArtifactStatus
from app.domain.projects import Project
from app.main import create_app
from app.providers.blob_storage import StoredBlobProperties
from app.repositories.uploads import PendingUploadRejection, PendingUploadResult

OWNER_ID = UUID("0c3d60a8-5117-44e5-821b-abc1c0c8f3d0")
OTHER_OWNER_ID = UUID("6e43e80d-9276-4d37-af4f-12f7f85d4f50")
SHA256 = "a" * 64


class FakeProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}

    async def create(self, *, owner_id: UUID, name: str) -> Project:
        now = datetime.now(UTC)
        project = Project(
            id=uuid4(),
            owner_id=owner_id,
            name=name,
            created_at=now,
            updated_at=now,
        )
        self.projects[project.id] = project
        return project

    async def get_for_owner(self, *, project_id: UUID, owner_id: UUID) -> Project | None:
        project = self.projects.get(project_id)
        return project if project is not None and project.owner_id == owner_id else None

    async def list_for_owner(self, *, owner_id: UUID) -> list[Project]:
        return [project for project in self.projects.values() if project.owner_id == owner_id]


class FakeUploadRepository:
    def __init__(self, projects: FakeProjectRepository) -> None:
        self.projects = projects
        self.artifacts: dict[UUID, tuple[UUID, Artifact]] = {}
        self.quota_exceeded = False
        self.last_blob_name: str | None = None
        self.last_quota_started_at: datetime | None = None
        self.last_quota_window: timedelta | None = None
        self.last_quota_limit: int | None = None

    async def create_pending(
        self,
        *,
        artifact_id: UUID,
        owner_id: UUID,
        project_id: UUID,
        blob_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        expires_at: datetime,
        quota_started_at: datetime,
        quota_window: timedelta,
        quota_limit: int,
    ) -> PendingUploadResult:
        self.last_quota_started_at = quota_started_at
        self.last_quota_window = quota_window
        self.last_quota_limit = quota_limit
        if await self.projects.get_for_owner(project_id=project_id, owner_id=owner_id) is None:
            return PendingUploadResult(rejection=PendingUploadRejection.PROJECT_NOT_FOUND)
        if self.quota_exceeded:
            return PendingUploadResult(
                rejection=PendingUploadRejection.QUOTA_EXCEEDED,
                retry_at=datetime.now(UTC) + quota_window,
            )
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            kind="source_image",
            blob_name=blob_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            status=ArtifactStatus.PENDING,
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
        self.last_blob_name = blob_name
        self.artifacts[artifact_id] = (owner_id, artifact)
        return PendingUploadResult(artifact=artifact)

    async def get_for_owner(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None:
        stored = self.artifacts.get(artifact_id)
        return stored[1] if stored is not None and stored[0] == owner_id else None

    async def mark_ready(self, *, artifact_id: UUID, owner_id: UUID) -> Artifact | None:
        artifact = await self.get_for_owner(artifact_id=artifact_id, owner_id=owner_id)
        if artifact is None:
            return None
        ready = replace(artifact, status=ArtifactStatus.READY, expires_at=None)
        self.artifacts[artifact_id] = (owner_id, ready)
        return ready


class FakeBlobStorage:
    def __init__(self) -> None:
        self.created_blob_name: str | None = None
        self.sas_expires_at: datetime | None = None
        self.properties: dict[str, StoredBlobProperties] = {}
        self.properties_requests = 0

    async def create_upload_url(self, *, blob_name: str, expires_at: datetime) -> str:
        self.created_blob_name = blob_name
        self.sas_expires_at = expires_at
        return f"https://storage.example.test/container/{blob_name}?sig=secret"

    async def get_properties(self, *, blob_name: str) -> StoredBlobProperties | None:
        self.properties_requests += 1
        return self.properties.get(blob_name)


@pytest.fixture
def api_context() -> tuple[
    httpx.AsyncClient,
    FakeProjectRepository,
    FakeUploadRepository,
    FakeBlobStorage,
]:
    projects = FakeProjectRepository()
    uploads = FakeUploadRepository(projects)
    blob_storage = FakeBlobStorage()
    app = create_app(
        Settings(
            upload_max_image_size_bytes=100,
            upload_quota_limit=30,
            upload_quota_window_hours=24,
            upload_pending_lifetime_hours=24,
            upload_sas_lifetime_minutes=10,
        )
    )

    async def current_user() -> AuthenticatedUser:
        return AuthenticatedUser(
            id=str(OWNER_ID),
            email="builder@example.com",
            display_name=None,
            avatar_url=None,
        )

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_upload_repository] = lambda: uploads
    app.dependency_overrides[get_blob_storage] = lambda: blob_storage
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, projects, uploads, blob_storage


async def create_owned_project(projects: FakeProjectRepository) -> Project:
    return await projects.create(owner_id=OWNER_ID, name="Castle")


def upload_body(project_id: UUID, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "projectId": str(project_id),
        "fileName": "castle.png",
        "mimeType": "image/png",
        "sizeBytes": 80,
        "sha256": SHA256,
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_authenticated_project_creation_and_listing_are_owner_scoped(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, _, _ = api_context
    await projects.create(owner_id=OTHER_OWNER_ID, name="Private project")

    response = await client.post("/api/v1/projects", json={"name": "  Castle  "})
    listing = await client.get("/api/v1/projects")
    await client.aclose()

    assert response.status_code == 201
    assert response.json()["name"] == "Castle"
    assert [project["name"] for project in listing.json()] == ["Castle"]


@pytest.mark.asyncio
async def test_project_name_cannot_be_empty(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, _, _, _ = api_context
    response = await client.post("/api/v1/projects", json={"name": "   "})
    await client.aclose()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_requires_authentication() -> None:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/uploads", json=upload_body(uuid4()))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_does_not_reveal_missing_or_other_users_projects(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, _, _ = api_context
    other_project = await projects.create(owner_id=OTHER_OWNER_ID, name="Other")

    missing = await client.post("/api/v1/uploads", json=upload_body(uuid4()))
    other_user = await client.post("/api/v1/uploads", json=upload_body(other_project.id))
    await client.aclose()

    assert missing.status_code == 404
    assert other_user.status_code == 404
    assert missing.json() == other_user.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"mimeType": "image/gif"}, 422),
        ({"sizeBytes": 101}, 413),
        ({"sizeBytes": 0}, 422),
        ({"sha256": "not-a-hash"}, 422),
        ({"fileName": "../image.png"}, 422),
    ],
)
async def test_upload_rejects_invalid_metadata(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
    overrides: dict[str, object],
    expected_status: int,
) -> None:
    client, projects, _, _ = api_context
    project = await create_owned_project(projects)
    response = await client.post("/api/v1/uploads", json=upload_body(project.id, **overrides))
    await client.aclose()
    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_rolling_upload_quota_returns_retry_after(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, uploads, _ = api_context
    project = await create_owned_project(projects)
    uploads.quota_exceeded = True
    before = datetime.now(UTC)

    response = await client.post("/api/v1/uploads", json=upload_body(project.id))
    await client.aclose()

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    assert uploads.last_quota_limit == 30
    assert uploads.last_quota_window == timedelta(hours=24)
    assert uploads.last_quota_started_at is not None
    assert before - timedelta(hours=24, seconds=1) <= uploads.last_quota_started_at <= before


@pytest.mark.asyncio
async def test_valid_upload_creates_pending_artifact_and_scoped_sas(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, uploads, blob_storage = api_context
    project = await create_owned_project(projects)
    before = datetime.now(UTC)

    response = await client.post("/api/v1/uploads", json=upload_body(project.id))
    await client.aclose()

    assert response.status_code == 201
    upload_id = UUID(response.json()["uploadId"])
    artifact = uploads.artifacts[upload_id][1]
    assert artifact.status is ArtifactStatus.PENDING
    assert uploads.last_blob_name == f"projects/{project.id}/uploads/{upload_id}/castle.png"
    assert blob_storage.created_blob_name == uploads.last_blob_name
    assert blob_storage.sas_expires_at is not None
    assert before + timedelta(minutes=9, seconds=59) <= blob_storage.sas_expires_at
    assert response.json()["requiredHeaders"] == {
        "x-ms-blob-type": "BlockBlob",
        "Content-Type": "image/png",
        "x-ms-meta-sha256": SHA256,
    }


@pytest.mark.asyncio
async def test_client_cannot_supply_a_blob_path(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, _, _ = api_context
    project = await create_owned_project(projects)
    response = await client.post(
        "/api/v1/uploads",
        json=upload_body(project.id, blobName="attacker/chosen/path"),
    )
    await client.aclose()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_completion_verifies_blob_and_is_idempotent(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, uploads, blob_storage = api_context
    project = await create_owned_project(projects)
    initiated = await client.post("/api/v1/uploads", json=upload_body(project.id))
    upload_id = UUID(initiated.json()["uploadId"])
    artifact = uploads.artifacts[upload_id][1]
    blob_storage.properties[artifact.blob_name] = StoredBlobProperties(
        size_bytes=artifact.size_bytes,
        content_type=artifact.mime_type,
        sha256=artifact.sha256,
    )

    first = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    second = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    await client.aclose()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "ready"
    assert uploads.artifacts[upload_id][1].status is ArtifactStatus.READY
    assert blob_storage.properties_requests == 1


@pytest.mark.asyncio
async def test_missing_or_mismatched_blob_does_not_mark_upload_ready(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, uploads, blob_storage = api_context
    project = await create_owned_project(projects)
    initiated = await client.post("/api/v1/uploads", json=upload_body(project.id))
    upload_id = UUID(initiated.json()["uploadId"])
    artifact = uploads.artifacts[upload_id][1]

    missing = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    blob_storage.properties[artifact.blob_name] = StoredBlobProperties(
        size_bytes=artifact.size_bytes + 1,
        content_type=artifact.mime_type,
        sha256=artifact.sha256,
    )
    mismatched = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    await client.aclose()

    assert missing.status_code == 409
    assert mismatched.status_code == 409
    assert uploads.artifacts[upload_id][1].status is ArtifactStatus.PENDING


@pytest.mark.asyncio
async def test_another_user_cannot_complete_upload(
    api_context: tuple[
        httpx.AsyncClient,
        FakeProjectRepository,
        FakeUploadRepository,
        FakeBlobStorage,
    ],
) -> None:
    client, projects, uploads, _ = api_context
    project = await create_owned_project(projects)
    initiated = await client.post("/api/v1/uploads", json=upload_body(project.id))
    upload_id = UUID(initiated.json()["uploadId"])
    uploads.artifacts[upload_id] = (OTHER_OWNER_ID, uploads.artifacts[upload_id][1])

    response = await client.post(f"/api/v1/uploads/{upload_id}/complete")
    await client.aclose()
    assert response.status_code == 404
