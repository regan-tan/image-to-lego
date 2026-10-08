from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.projects import get_project_repository
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings
from app.domain.jobs import JobStatus
from app.domain.projects import (
    Project,
    ProjectOverview,
    ProjectReconstruction,
    ProjectSourceImage,
    ProjectStatus,
    project_status,
)
from app.main import create_app

OWNER_ID = UUID("0c3d60a8-5117-44e5-821b-abc1c0c8f3d0")
OTHER_OWNER_ID = UUID("6e43e80d-9276-4d37-af4f-12f7f85d4f50")
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def make_project(owner_id: UUID = OWNER_ID, name: str = "Toy robot") -> Project:
    return Project(id=uuid4(), owner_id=owner_id, name=name, created_at=NOW, updated_at=NOW)


def make_source_image() -> ProjectSourceImage:
    return ProjectSourceImage(
        artifact_id=uuid4(),
        mime_type="image/jpeg",
        size_bytes=2_516_582,
        created_at=NOW,
    )


def make_reconstruction(
    job_status: JobStatus,
    *,
    output_artifact_id: UUID | None = None,
    error_message: str | None = None,
) -> ProjectReconstruction:
    return ProjectReconstruction(
        job_id=uuid4(),
        status=job_status,
        output_artifact_id=output_artifact_id,
        error_code="provider_timeout" if error_message else None,
        error_message=error_message,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeProjectOverviewRepository:
    def __init__(self, overviews: list[ProjectOverview]) -> None:
        self.overviews = overviews

    async def create(self, *, owner_id: UUID, name: str) -> Project:
        raise AssertionError("Project creation is not used by these tests.")

    async def get_for_owner(self, *, project_id: UUID, owner_id: UUID) -> Project | None:
        raise AssertionError("Plain project lookup is not used by these tests.")

    async def get_overview_for_owner(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
    ) -> ProjectOverview | None:
        for overview in self.overviews:
            if overview.project.id == project_id and overview.project.owner_id == owner_id:
                return overview
        return None

    async def list_overviews_for_owner(self, *, owner_id: UUID) -> list[ProjectOverview]:
        return [overview for overview in self.overviews if overview.project.owner_id == owner_id]


def client_for(overviews: list[ProjectOverview]) -> httpx.AsyncClient:
    app = create_app(Settings())

    async def current_user() -> AuthenticatedUser:
        return AuthenticatedUser(
            id=str(OWNER_ID),
            email="builder@example.com",
            display_name=None,
            avatar_url=None,
        )

    repository = FakeProjectOverviewRepository(overviews)
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_project_repository] = lambda: repository
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize(
    ("job_status", "expected"),
    [
        (JobStatus.QUEUED, ProjectStatus.GENERATING),
        (JobStatus.RUNNING, ProjectStatus.GENERATING),
        (JobStatus.SUCCEEDED, ProjectStatus.MODEL_READY),
        (JobStatus.FAILED, ProjectStatus.FAILED),
        (JobStatus.CANCELED, ProjectStatus.FAILED),
    ],
)
def test_project_status_follows_the_current_photo_reconstruction(
    job_status: JobStatus,
    expected: ProjectStatus,
) -> None:
    assert project_status(make_source_image(), make_reconstruction(job_status)) == expected


def test_project_without_a_ready_photo_needs_one() -> None:
    assert project_status(None, None) == ProjectStatus.NEEDS_PHOTO


def test_project_with_a_ready_photo_and_no_job_is_ready_to_generate() -> None:
    assert project_status(make_source_image(), None) == ProjectStatus.PHOTO_READY


@pytest.mark.asyncio
async def test_project_list_includes_each_projects_status_and_is_owner_scoped() -> None:
    sneaker_photo = make_source_image()
    generating = ProjectOverview(
        make_project(name="Sneaker"),
        sneaker_photo,
        make_reconstruction(JobStatus.RUNNING),
    )
    empty = ProjectOverview(make_project(name="Desk lamp"), None, None)
    other_users = ProjectOverview(make_project(OTHER_OWNER_ID, "Private"), None, None)

    async with client_for([generating, empty, other_users]) as client:
        response = await client.get("/api/v1/projects")

    assert response.status_code == 200
    assert [(project["name"], project["status"]) for project in response.json()] == [
        ("Sneaker", "generating"),
        ("Desk lamp", "needs_photo"),
    ]
    assert response.json()[0]["sourceImageArtifactId"] == str(sneaker_photo.artifact_id)
    assert response.json()[1]["sourceImageArtifactId"] is None


@pytest.mark.asyncio
async def test_project_detail_returns_latest_photo_and_reconstruction() -> None:
    source_image = make_source_image()
    output_artifact_id = uuid4()
    reconstruction = make_reconstruction(
        JobStatus.SUCCEEDED,
        output_artifact_id=output_artifact_id,
    )
    overview = ProjectOverview(make_project(), source_image, reconstruction)

    async with client_for([overview]) as client:
        response = await client.get(f"/api/v1/projects/{overview.project.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(overview.project.id),
        "name": "Toy robot",
        "status": "model_ready",
        "sourceImageArtifactId": str(source_image.artifact_id),
        "createdAt": "2026-10-08T09:00:00Z",
        "updatedAt": "2026-10-08T09:00:00Z",
        "sourceImage": {
            "artifactId": str(source_image.artifact_id),
            "mimeType": "image/jpeg",
            "sizeBytes": 2_516_582,
            "createdAt": "2026-10-08T09:00:00Z",
        },
        "latestReconstruction": {
            "jobId": str(reconstruction.job_id),
            "status": "succeeded",
            "outputArtifactId": str(output_artifact_id),
            "errorCode": None,
            "errorMessage": None,
            "createdAt": "2026-10-08T09:00:00Z",
            "updatedAt": "2026-10-08T09:00:00Z",
        },
    }


@pytest.mark.asyncio
async def test_project_detail_without_photo_or_job_returns_nulls() -> None:
    overview = ProjectOverview(make_project(), None, None)

    async with client_for([overview]) as client:
        response = await client.get(f"/api/v1/projects/{overview.project.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "needs_photo"
    assert response.json()["sourceImage"] is None
    assert response.json()["latestReconstruction"] is None


@pytest.mark.asyncio
async def test_project_detail_reports_a_failed_generation_with_its_safe_reason() -> None:
    overview = ProjectOverview(
        make_project(),
        make_source_image(),
        make_reconstruction(
            JobStatus.FAILED,
            error_message="The generation did not finish in time.",
        ),
    )

    async with client_for([overview]) as client:
        response = await client.get(f"/api/v1/projects/{overview.project.id}")

    assert response.json()["status"] == "failed"
    assert response.json()["latestReconstruction"]["errorMessage"] == (
        "The generation did not finish in time."
    )


@pytest.mark.asyncio
async def test_project_detail_does_not_reveal_missing_or_other_users_projects() -> None:
    other_users = ProjectOverview(make_project(OTHER_OWNER_ID, "Private"), None, None)

    async with client_for([other_users]) as client:
        missing = await client.get(f"/api/v1/projects/{uuid4()}")
        not_owned = await client.get(f"/api/v1/projects/{other_users.project.id}")

    assert missing.status_code == 404
    assert not_owned.status_code == 404
    assert missing.json() == not_owned.json()


@pytest.mark.asyncio
async def test_project_detail_rejects_a_malformed_project_id() -> None:
    async with client_for([]) as client:
        response = await client.get("/api/v1/projects/not-a-uuid")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_project_detail_requires_authentication() -> None:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{uuid4()}")

    assert response.status_code == 401
