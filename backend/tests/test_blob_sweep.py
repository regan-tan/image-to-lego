from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.providers.blob_storage import ListedBlob
from app.workers.blob_sweep import OrphanedProjectFolder, sweep_orphaned_blobs

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
MIN_AGE = timedelta(minutes=60)
OLD = NOW - timedelta(hours=2)
RECENT = NOW - timedelta(minutes=5)

LIVE_PROJECT_ID = UUID("11111111-1111-4111-8111-111111111111")
DELETED_PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")


class FakeSweepBlobStorage:
    def __init__(self, blobs: list[ListedBlob]) -> None:
        self.blobs = {blob.name: blob for blob in blobs}
        self.listed_prefixes: list[str] = []

    async def list_blobs(self, *, prefix: str) -> list[ListedBlob]:
        self.listed_prefixes.append(prefix)
        return [blob for name, blob in self.blobs.items() if name.startswith(prefix)]

    async def delete_blob(self, *, blob_name: str) -> None:
        self.blobs.pop(blob_name, None)


class FakeProjectExistenceRepository:
    def __init__(self, existing_ids: set[UUID]) -> None:
        self.existing_ids = existing_ids
        self.candidate_ids: list[UUID] | None = None

    async def existing_project_ids(self, *, candidate_ids: list[UUID]) -> set[UUID]:
        self.candidate_ids = candidate_ids
        return self.existing_ids & set(candidate_ids)


def blob(name: str, last_modified: datetime = OLD) -> ListedBlob:
    return ListedBlob(name=name, last_modified=last_modified)


DELETED_PROJECT_BLOBS = [
    blob(f"projects/{DELETED_PROJECT_ID}/uploads/a/cat.jpg"),
    blob(f"projects/{DELETED_PROJECT_ID}/reconstructions/b/model.glb"),
]
LIVE_PROJECT_BLOB = blob(f"projects/{LIVE_PROJECT_ID}/uploads/c/castle.png")


async def sweep(
    storage: FakeSweepBlobStorage,
    projects: FakeProjectExistenceRepository,
    *,
    delete: bool,
) -> list[OrphanedProjectFolder]:
    return await sweep_orphaned_blobs(
        blob_storage=storage,
        projects=projects,
        now=NOW,
        min_age=MIN_AGE,
        delete=delete,
    )


@pytest.mark.asyncio
async def test_report_mode_finds_deleted_project_folder_without_deleting() -> None:
    storage = FakeSweepBlobStorage([*DELETED_PROJECT_BLOBS, LIVE_PROJECT_BLOB])
    projects = FakeProjectExistenceRepository({LIVE_PROJECT_ID})

    orphaned = await sweep(storage, projects, delete=False)

    assert orphaned == [
        OrphanedProjectFolder(
            DELETED_PROJECT_ID,
            (
                f"projects/{DELETED_PROJECT_ID}/reconstructions/b/model.glb",
                f"projects/{DELETED_PROJECT_ID}/uploads/a/cat.jpg",
            ),
        )
    ]
    assert len(storage.blobs) == 3
    assert storage.listed_prefixes == ["projects/"]
    assert set(projects.candidate_ids or []) == {LIVE_PROJECT_ID, DELETED_PROJECT_ID}


@pytest.mark.asyncio
async def test_delete_mode_removes_only_the_deleted_project_folder() -> None:
    storage = FakeSweepBlobStorage([*DELETED_PROJECT_BLOBS, LIVE_PROJECT_BLOB])
    projects = FakeProjectExistenceRepository({LIVE_PROJECT_ID})

    await sweep(storage, projects, delete=True)

    assert list(storage.blobs) == [LIVE_PROJECT_BLOB.name]


@pytest.mark.asyncio
async def test_running_the_sweep_twice_is_harmless() -> None:
    storage = FakeSweepBlobStorage([*DELETED_PROJECT_BLOBS, LIVE_PROJECT_BLOB])
    projects = FakeProjectExistenceRepository({LIVE_PROJECT_ID})

    await sweep(storage, projects, delete=True)
    second_run = await sweep(storage, projects, delete=True)

    assert second_run == []
    assert list(storage.blobs) == [LIVE_PROJECT_BLOB.name]


@pytest.mark.asyncio
async def test_folder_with_a_recent_blob_waits_for_a_later_sweep() -> None:
    recent_upload = blob(f"projects/{DELETED_PROJECT_ID}/uploads/d/late.png", RECENT)
    storage = FakeSweepBlobStorage([*DELETED_PROJECT_BLOBS, recent_upload])
    projects = FakeProjectExistenceRepository(set())

    orphaned = await sweep(storage, projects, delete=True)

    assert orphaned == []
    assert len(storage.blobs) == 3


@pytest.mark.asyncio
async def test_names_outside_project_uuid_folders_are_never_deleted() -> None:
    unexpected = [
        blob("projects/not-a-uuid/uploads/a/cat.jpg"),
        blob(f"projects/{DELETED_PROJECT_ID}"),
        blob("exports/report.csv"),
    ]
    storage = FakeSweepBlobStorage(unexpected)
    projects = FakeProjectExistenceRepository(set())

    orphaned = await sweep(storage, projects, delete=True)

    assert orphaned == []
    assert len(storage.blobs) == 3
    assert projects.candidate_ids is None
