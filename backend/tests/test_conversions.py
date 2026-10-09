import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
import trimesh

from app.api.v1.conversions import get_conversion_queue, get_conversion_repository
from app.api.v1.reconstructions import get_job_repository
from app.conversion import Axis, ConversionSettings, convert_glb
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings
from app.domain.artifacts import Artifact, ArtifactStatus
from app.domain.jobs import ConversionJob, Job, JobStatus, JobType, WorkerConversionJob
from app.main import create_app
from app.providers.blob_storage import BlobStorageError, StoredBlobProperties
from app.providers.conversion_queue import ConversionQueueError
from app.repositories.conversion import ConversionInitiation, ConversionInitiationRejection
from app.workers.conversion_worker import ConversionJobProcessor, serialize_lego_model

OWNER_ID = UUID("0c3d60a8-5117-44e5-821b-abc1c0c8f3d0")
OTHER_OWNER_ID = UUID("6e43e80d-9276-4d37-af4f-12f7f85d4f50")
PROJECT_ID = UUID("eb4d4208-4c79-4bb4-a636-329a37ee5c24")
SOURCE_ID = UUID("6817a1e8-e37b-4565-a004-038e01fe8d3f")


def box_glb() -> bytes:
    exported = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(exported, bytes)
    return exported


def conversion_job(
    *,
    status: JobStatus = JobStatus.QUEUED,
    source_artifact_id: UUID = SOURCE_ID,
    target_parts: int = 24,
    up_axis: str = "y",
    output_artifact_id: UUID | None = None,
) -> ConversionJob:
    now = datetime.now(UTC)
    return ConversionJob(
        job=Job(
            id=uuid4(),
            project_id=PROJECT_ID,
            type=JobType.CONVERSION,
            status=status,
            idempotency_key="request-key",
            provider_job_id=None,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        ),
        source_artifact_id=source_artifact_id,
        target_parts=target_parts,
        up_axis=up_axis,
        output_artifact_id=output_artifact_id,
    )


class FakeConversionRepository:
    def __init__(self) -> None:
        self.initiation = ConversionInitiation(conversion=conversion_job(), created=True)
        self.queue_failures = 0
        self.worker_job: WorkerConversionJob | None = None
        self.claimed = True
        self.claims = 0
        self.failures: list[tuple[str, str]] = []
        self.created_outputs: list[dict[str, object]] = []
        self.succeeded = 0

    async def create_or_get(self, **_: object) -> ConversionInitiation:
        return self.initiation

    async def mark_queue_publish_failed(self, **_: object) -> None:
        self.queue_failures += 1

    async def get_for_owner(self, *, job_id: UUID, owner_id: UUID) -> ConversionJob | None:
        conversion = self.initiation.conversion
        if owner_id != OWNER_ID or conversion is None or conversion.job.id != job_id:
            return None
        return conversion

    async def get_for_worker(self, **_: object) -> WorkerConversionJob | None:
        return self.worker_job

    async def claim(self, **_: object) -> bool:
        self.claims += 1
        return self.claimed

    async def mark_failed(
        self,
        *,
        error_code: str,
        error_message: str,
        **_: object,
    ) -> None:
        self.failures.append((error_code, error_message))

    async def create_output_artifact(self, **kwargs: object) -> UUID:
        self.created_outputs.append(kwargs)
        return uuid4()

    async def mark_succeeded(self, **_: object) -> None:
        self.succeeded += 1


class FakeConversionQueue:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.enqueued: list[tuple[UUID, UUID]] = []

    async def enqueue(self, *, job_id: UUID, owner_id: UUID) -> None:
        if self.should_fail:
            raise ConversionQueueError("unavailable")
        self.enqueued.append((job_id, owner_id))


class FakeBlobStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.downloads = 0
        self.uploads: list[tuple[str, bytes, str, str]] = []
        self.reuse_existing = False
        self.collision = False
        self.download_error: BlobStorageError | None = None

    async def download_bounded(self, **_: object) -> bytes:
        self.downloads += 1
        if self.download_error is not None:
            raise self.download_error
        return self.content

    async def create_upload_url(self, **_: object) -> str:
        return "https://storage.example.test/upload"

    async def create_read_url(self, **_: object) -> str:
        return "https://storage.example.test/read"

    async def upload_generated_artifact(
        self,
        *,
        blob_name: str,
        content: bytes,
        mime_type: str,
        sha256: str,
    ) -> bool:
        self.uploads.append((blob_name, content, mime_type, sha256))
        return not self.reuse_existing

    async def get_properties(self, **_: object) -> StoredBlobProperties | None:
        if not self.uploads:
            return None
        blob_name, content, mime_type, sha256 = self.uploads[-1]
        assert blob_name
        if self.collision:
            return StoredBlobProperties(
                size_bytes=len(content), content_type="text/plain", sha256=sha256
            )
        return StoredBlobProperties(size_bytes=len(content), content_type=mime_type, sha256=sha256)


def worker_job(
    content: bytes,
    *,
    status: JobStatus = JobStatus.QUEUED,
    output_artifact_id: UUID | None = None,
) -> WorkerConversionJob:
    source = Artifact(
        id=SOURCE_ID,
        project_id=PROJECT_ID,
        kind="reconstructed_model",
        blob_name="projects/source/model.glb",
        mime_type="model/gltf-binary",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        status=ArtifactStatus.READY,
        expires_at=None,
        created_at=datetime.now(UTC),
    )
    return WorkerConversionJob(
        conversion=conversion_job(status=status, output_artifact_id=output_artifact_id),
        owner_id=OWNER_ID,
        source_artifact=source,
    )


@pytest.fixture
def api_context() -> tuple[httpx.AsyncClient, FakeConversionRepository, FakeConversionQueue]:
    repository = FakeConversionRepository()
    queue = FakeConversionQueue()
    app = create_app(Settings())

    async def current_user() -> AuthenticatedUser:
        return AuthenticatedUser(str(OWNER_ID), None, None, None)

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_conversion_repository] = lambda: repository
    app.dependency_overrides[get_conversion_queue] = lambda: queue
    app.dependency_overrides[get_job_repository] = lambda: repository
    return (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"),
        repository,
        queue,
    )


def request_body(**overrides: str | int) -> dict[str, str | int]:
    body: dict[str, str | int] = {
        "projectId": str(PROJECT_ID),
        "sourceArtifactId": str(SOURCE_ID),
        "targetParts": 24,
        "upAxis": "y",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_conversion_create_and_exact_replay_publish_once(
    api_context: tuple[httpx.AsyncClient, FakeConversionRepository, FakeConversionQueue],
) -> None:
    client, repository, queue = api_context
    created = await client.post(
        "/api/v1/conversions", headers={"Idempotency-Key": "key"}, json=request_body()
    )
    repository.initiation = ConversionInitiation(
        conversion=repository.initiation.conversion,
        created=False,
    )
    replayed = await client.post(
        "/api/v1/conversions", headers={"Idempotency-Key": "key"}, json=request_body()
    )
    await client.aclose()
    assert created.status_code == 201
    assert replayed.status_code == 200
    assert len(queue.enqueued) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rejection", "expected_status"),
    [
        (ConversionInitiationRejection.NOT_FOUND, 404),
        (ConversionInitiationRejection.WRONG_ARTIFACT_KIND, 422),
        (ConversionInitiationRejection.SOURCE_NOT_READY, 409),
        (ConversionInitiationRejection.IDEMPOTENCY_CONFLICT, 409),
    ],
)
async def test_conversion_rejects_other_owner_invalid_or_not_ready_source(
    api_context: tuple[httpx.AsyncClient, FakeConversionRepository, FakeConversionQueue],
    rejection: ConversionInitiationRejection,
    expected_status: int,
) -> None:
    client, repository, _ = api_context
    repository.initiation = ConversionInitiation(rejection=rejection)
    response = await client.post(
        "/api/v1/conversions", headers={"Idempotency-Key": "key"}, json=request_body()
    )
    await client.aclose()
    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_conversion_queue_failure_marks_new_job_failed(
    api_context: tuple[httpx.AsyncClient, FakeConversionRepository, FakeConversionQueue],
) -> None:
    client, repository, queue = api_context
    queue.should_fail = True
    response = await client.post(
        "/api/v1/conversions", headers={"Idempotency-Key": "key"}, json=request_body()
    )
    await client.aclose()
    assert response.status_code == 503
    assert repository.queue_failures == 1


@pytest.mark.asyncio
async def test_get_job_returns_a_conversion_status_for_its_owner(
    api_context: tuple[httpx.AsyncClient, FakeConversionRepository, FakeConversionQueue],
) -> None:
    client, repository, _ = api_context
    conversion = repository.initiation.conversion
    assert conversion is not None
    response = await client.get(f"/api/v1/jobs/{conversion.job.id}")
    await client.aclose()
    assert response.status_code == 200
    assert response.json()["type"] == "conversion"


@pytest.mark.asyncio
async def test_worker_stores_one_canonical_lego_model() -> None:
    content = box_glb()
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(content)
    blob = FakeBlobStorage(content)
    await ConversionJobProcessor(repository=repository, blob_storage=blob).process(
        job_id=repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert repository.claims == 1
    assert repository.succeeded == 1
    assert len(repository.created_outputs) == 1
    expected_blob_suffix = f"/conversions/{repository.worker_job.conversion.job.id}/lego-model.json"
    assert blob.uploads[0][0].endswith(expected_blob_suffix)
    output = json.loads(blob.uploads[0][1])
    assert output["partCount"] == len(output["placements"])
    assert output["placements"][0]["brickType"]


def test_lego_model_json_is_stable() -> None:
    model = convert_glb(box_glb(), ConversionSettings(target_parts=24, up_axis=Axis.Y))
    first = serialize_lego_model(model)
    second = serialize_lego_model(model)
    assert first == second
    assert json.loads(first)["metadata"]["algorithmVersion"] == model.metadata.algorithm_version


@pytest.mark.asyncio
async def test_worker_fails_when_source_sha256_does_not_match() -> None:
    content = box_glb()
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(content)
    repository.worker_job = WorkerConversionJob(
        conversion=repository.worker_job.conversion,
        owner_id=OWNER_ID,
        source_artifact=replace(repository.worker_job.source_artifact, sha256="0" * 64),
    )
    blob = FakeBlobStorage(content)
    await ConversionJobProcessor(repository=repository, blob_storage=blob).process(
        job_id=repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert repository.failures[0][0] == "conversion_source_integrity_failed"
    assert not blob.uploads


@pytest.mark.asyncio
async def test_running_job_without_output_resumes_without_claiming_again() -> None:
    content = box_glb()
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(content, status=JobStatus.RUNNING)
    repository.claimed = False
    blob = FakeBlobStorage(content)
    await ConversionJobProcessor(repository=repository, blob_storage=blob).process(
        job_id=repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert repository.claims == 0
    assert repository.succeeded == 1
    assert len(repository.created_outputs) == 1


@pytest.mark.asyncio
async def test_running_job_with_existing_output_is_marked_succeeded_without_reconverting() -> None:
    content = box_glb()
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(
        content,
        status=JobStatus.RUNNING,
        output_artifact_id=uuid4(),
    )
    blob = FakeBlobStorage(content)
    await ConversionJobProcessor(repository=repository, blob_storage=blob).process(
        job_id=repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert repository.claims == 0
    assert repository.succeeded == 1
    assert blob.downloads == 0
    assert not blob.uploads
    assert not repository.created_outputs


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED])
async def test_terminal_duplicate_delivery_is_a_no_op(status: JobStatus) -> None:
    content = box_glb()
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(content, status=status)
    blob = FakeBlobStorage(content)
    await ConversionJobProcessor(repository=repository, blob_storage=blob).process(
        job_id=repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert repository.claims == 0
    assert repository.succeeded == 0
    assert blob.downloads == 0
    assert not blob.uploads
    assert not repository.created_outputs


@pytest.mark.asyncio
async def test_redelivered_running_job_does_not_create_a_second_output() -> None:
    content = box_glb()
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(content, status=JobStatus.RUNNING)
    blob = FakeBlobStorage(content)
    processor = ConversionJobProcessor(repository=repository, blob_storage=blob)
    await processor.process(job_id=repository.worker_job.conversion.job.id, owner_id=OWNER_ID)

    completed_job = repository.worker_job
    repository.worker_job = replace(
        completed_job,
        conversion=replace(completed_job.conversion, output_artifact_id=uuid4()),
    )
    await processor.process(job_id=repository.worker_job.conversion.job.id, owner_id=OWNER_ID)

    assert len(repository.created_outputs) == 1
    assert repository.succeeded == 2
    assert len(blob.uploads) == 1


@pytest.mark.asyncio
async def test_worker_reuses_matching_canonical_blob_and_rejects_collision() -> None:
    content = box_glb()
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(content)
    blob = FakeBlobStorage(content)
    blob.reuse_existing = True
    await ConversionJobProcessor(repository=repository, blob_storage=blob).process(
        job_id=repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert repository.succeeded == 1
    assert len(repository.created_outputs) == 1

    collision_repository = FakeConversionRepository()
    collision_repository.worker_job = worker_job(content)
    collision_blob = FakeBlobStorage(content)
    collision_blob.reuse_existing = True
    collision_blob.collision = True
    collision_processor = ConversionJobProcessor(
        repository=collision_repository,
        blob_storage=collision_blob,
    )
    await collision_processor.process(
        job_id=collision_repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert collision_repository.failures[0][0] == "canonical_lego_model_conflict"
    assert not collision_repository.created_outputs


@pytest.mark.asyncio
async def test_invalid_glb_becomes_a_safe_failed_job() -> None:
    content = b"not-a-glb"
    repository = FakeConversionRepository()
    repository.worker_job = worker_job(content)
    blob = FakeBlobStorage(content)
    await ConversionJobProcessor(repository=repository, blob_storage=blob).process(
        job_id=repository.worker_job.conversion.job.id,
        owner_id=OWNER_ID,
    )
    assert repository.failures[0][0] == "conversion_failed"
    assert not blob.uploads
