import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.v1.reconstructions import get_generation_queue, get_reconstruction_repository
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.artifacts import Artifact, ArtifactStatus
from app.domain.jobs import Job, JobStatus, JobType, ReconstructionJob, WorkerReconstructionJob
from app.main import create_app
from app.providers.blob_storage import BlobNotFoundError, BlobStorageError, StoredBlobProperties
from app.providers.generation_queue import GenerationQueueError
from app.providers.reconstruction import (
    ReconstructionOutput,
    ReconstructionRequest,
    ReconstructionState,
    ReconstructionStatus,
    ReconstructionSubmission,
)
from app.repositories.reconstruction import (
    ReconstructionInitiation,
    ReconstructionInitiationRejection,
)
from app.workers.generation_worker import GenerationJobProcessor, ModelDownloader, _parse_message

OWNER_ID = UUID("0c3d60a8-5117-44e5-821b-abc1c0c8f3d0")
OTHER_OWNER_ID = UUID("6e43e80d-9276-4d37-af4f-12f7f85d4f50")
PROJECT_ID = UUID("eb4d4208-4c79-4bb4-a636-329a37ee5c24")
SOURCE_ID = UUID("6817a1e8-e37b-4565-a004-038e01fe8d3f")
PNG_CONTENT = b"\x89PNG\r\n\x1a\nsource"


def glb_bytes(*, version: int = 2, declared_length: int | None = None) -> bytes:
    content = b"glTF" + version.to_bytes(4, "little") + (12).to_bytes(4, "little")
    if declared_length is None:
        return content
    return content[:8] + declared_length.to_bytes(4, "little")


def reconstruction_job(
    *,
    status: JobStatus = JobStatus.QUEUED,
    provider_job_id: str | None = None,
    output_artifact_id: UUID | None = None,
    updated_at: datetime | None = None,
) -> ReconstructionJob:
    now = datetime.now(UTC)
    return ReconstructionJob(
        job=Job(
            id=uuid4(),
            project_id=PROJECT_ID,
            type=JobType.RECONSTRUCTION,
            status=status,
            idempotency_key="request-key",
            provider_job_id=provider_job_id,
            error_code="provider_failed" if status is JobStatus.FAILED else None,
            error_message="The provider failed." if status is JobStatus.FAILED else None,
            created_at=now,
            updated_at=updated_at or now,
        ),
        source_artifact_id=SOURCE_ID,
        output_artifact_id=output_artifact_id,
    )


class FakeReconstructionRepository:
    def __init__(self) -> None:
        self.initiation = ReconstructionInitiation(
            reconstruction=reconstruction_job(),
            created=True,
        )
        self.queue_failures = 0
        self.worker_job: WorkerReconstructionJob | None = None
        self.claimed = True
        self.persisted_provider_ids: list[str] = []
        self.terminal_states: list[tuple[str, str | None]] = []
        self.created_outputs = 0
        self.succeeded = False

    async def create_or_get(self, **_: object) -> ReconstructionInitiation:
        return self.initiation

    async def mark_queue_publish_failed(self, **_: object) -> None:
        self.queue_failures += 1

    async def get_for_owner(self, *, job_id: UUID, owner_id: UUID) -> ReconstructionJob | None:
        if owner_id != OWNER_ID or self.initiation.reconstruction is None:
            return None
        job = self.initiation.reconstruction
        return job if job.job.id == job_id else None

    async def get_for_worker(self, **_: object) -> WorkerReconstructionJob | None:
        return self.worker_job

    async def claim_provider_submission(self, **_: object) -> bool:
        return self.claimed

    async def persist_provider_job_id(self, *, provider_job_id: str, **_: object) -> None:
        self.persisted_provider_ids.append(provider_job_id)

    async def mark_terminal(
        self,
        *,
        status: str,
        error_code: str | None = None,
        **_: object,
    ) -> None:
        self.terminal_states.append((status, error_code))

    async def create_output_artifact(self, **_: object) -> UUID:
        self.created_outputs += 1
        return uuid4()

    async def mark_succeeded(self, **_: object) -> None:
        self.succeeded = True


class FakeGenerationQueue:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.enqueued: list[UUID] = []
        self.scheduled: list[UUID] = []

    async def enqueue(self, *, job_id: UUID, owner_id: UUID) -> None:
        if self.should_fail:
            raise GenerationQueueError("unavailable")
        assert owner_id == OWNER_ID
        self.enqueued.append(job_id)

    async def schedule(self, *, job_id: UUID, owner_id: UUID, scheduled_for: datetime) -> None:
        assert owner_id == OWNER_ID
        assert scheduled_for > datetime.now(UTC) - timedelta(seconds=1)
        self.scheduled.append(job_id)


class FakeBlobStorage:
    def __init__(self, content: bytes = PNG_CONTENT) -> None:
        self.content = content
        self.read_urls = 0
        self.uploaded: list[tuple[str, bytes, str, str]] = []
        self.upload_result = True
        self.existing_properties: StoredBlobProperties | None = None
        self.download_error: BlobStorageError | None = None

    async def download_bounded(self, **_: object) -> bytes:
        if self.download_error is not None:
            raise self.download_error
        return self.content

    async def create_upload_url(self, **_: object) -> str:
        return "https://storage.example.test/upload?sig=secret"

    async def get_properties(self, **_: object) -> StoredBlobProperties | None:
        return self.existing_properties

    async def create_read_url(self, **_: object) -> str:
        self.read_urls += 1
        return "https://storage.example.test/input?sig=secret"

    async def upload_generated_model(
        self,
        *,
        blob_name: str,
        content: bytes,
        mime_type: str,
        sha256: str,
    ) -> bool:
        self.uploaded.append((blob_name, content, mime_type, sha256))
        return self.upload_result


class FakeProvider:
    def __init__(self, state: ReconstructionState = ReconstructionState.QUEUED) -> None:
        self.state = state
        self.submissions = 0
        self.status_error: ApplicationError | None = None
        self.result_error: ApplicationError | None = None

    async def submit(self, request: ReconstructionRequest) -> ReconstructionSubmission:
        self.submissions += 1
        return ReconstructionSubmission(
            provider_job_id="fal-request", state=ReconstructionState.QUEUED
        )

    async def get_status(self, provider_job_id: str) -> ReconstructionStatus:
        if self.status_error is not None:
            raise self.status_error
        return ReconstructionStatus(provider_job_id=provider_job_id, state=self.state)

    async def get_result(self, provider_job_id: str) -> ReconstructionOutput:
        if self.result_error is not None:
            raise self.result_error
        return ReconstructionOutput(url="https://v3b.fal.media/files/model.glb")

    async def cancel(self, provider_job_id: str) -> ReconstructionStatus:
        return ReconstructionStatus(
            provider_job_id=provider_job_id, state=ReconstructionState.CANCELED
        )


def worker_job(
    *,
    provider_job_id: str | None = None,
    status: JobStatus = JobStatus.QUEUED,
    updated_at: datetime | None = None,
    mime_type: str = "image/png",
) -> WorkerReconstructionJob:
    reconstruction = reconstruction_job(
        provider_job_id=provider_job_id,
        status=status,
        updated_at=updated_at,
    )
    source = Artifact(
        id=SOURCE_ID,
        project_id=PROJECT_ID,
        kind="source_image",
        blob_name="projects/source.png",
        mime_type=mime_type,
        size_bytes=len(PNG_CONTENT),
        sha256=hashlib.sha256(PNG_CONTENT).hexdigest(),
        status=ArtifactStatus.READY,
        expires_at=None,
        created_at=datetime.now(UTC),
    )
    return WorkerReconstructionJob(
        reconstruction=reconstruction, owner_id=OWNER_ID, source_artifact=source
    )


@pytest.fixture
def api_context() -> tuple[httpx.AsyncClient, FakeReconstructionRepository, FakeGenerationQueue]:
    repository = FakeReconstructionRepository()
    queue = FakeGenerationQueue()
    app = create_app(Settings())

    async def current_user() -> AuthenticatedUser:
        return AuthenticatedUser(str(OWNER_ID), None, None, None)

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_reconstruction_repository] = lambda: repository
    app.dependency_overrides[get_generation_queue] = lambda: queue
    return (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"),
        repository,
        queue,
    )


@pytest.mark.asyncio
async def test_reconstruction_requires_authentication() -> None:
    app = create_app(Settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/reconstructions",
            headers={"Idempotency-Key": "request-key"},
            json={"projectId": str(PROJECT_ID), "sourceArtifactId": str(SOURCE_ID)},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reconstruction_creates_and_replays_without_reenqueuing(
    api_context: tuple[httpx.AsyncClient, FakeReconstructionRepository, FakeGenerationQueue],
) -> None:
    client, repository, queue = api_context
    body = {"projectId": str(PROJECT_ID), "sourceArtifactId": str(SOURCE_ID)}
    created = await client.post(
        "/api/v1/reconstructions", headers={"Idempotency-Key": "key"}, json=body
    )
    repository.initiation = ReconstructionInitiation(
        reconstruction=repository.initiation.reconstruction,
        created=False,
    )
    replayed = await client.post(
        "/api/v1/reconstructions", headers={"Idempotency-Key": "key"}, json=body
    )
    await client.aclose()
    assert created.status_code == 201
    assert replayed.status_code == 200
    assert len(queue.enqueued) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rejection", "expected_status"),
    [
        (ReconstructionInitiationRejection.NOT_FOUND, 404),
        (ReconstructionInitiationRejection.WRONG_ARTIFACT_KIND, 422),
        (ReconstructionInitiationRejection.SOURCE_NOT_READY, 409),
        (ReconstructionInitiationRejection.IDEMPOTENCY_CONFLICT, 409),
    ],
)
async def test_reconstruction_maps_safe_validation_errors(
    api_context: tuple[httpx.AsyncClient, FakeReconstructionRepository, FakeGenerationQueue],
    rejection: ReconstructionInitiationRejection,
    expected_status: int,
) -> None:
    client, repository, _ = api_context
    repository.initiation = ReconstructionInitiation(rejection=rejection)
    response = await client.post(
        "/api/v1/reconstructions",
        headers={"Idempotency-Key": "key"},
        json={"projectId": str(PROJECT_ID), "sourceArtifactId": str(SOURCE_ID)},
    )
    await client.aclose()
    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_queue_publication_failure_marks_job_failed_and_returns_503(
    api_context: tuple[httpx.AsyncClient, FakeReconstructionRepository, FakeGenerationQueue],
) -> None:
    client, repository, queue = api_context
    queue.should_fail = True
    response = await client.post(
        "/api/v1/reconstructions",
        headers={"Idempotency-Key": "key"},
        json={"projectId": str(PROJECT_ID), "sourceArtifactId": str(SOURCE_ID)},
    )
    await client.aclose()
    assert response.status_code == 503
    assert repository.queue_failures == 1


@pytest.mark.asyncio
async def test_job_status_is_owner_scoped_and_exposes_safe_fields(
    api_context: tuple[httpx.AsyncClient, FakeReconstructionRepository, FakeGenerationQueue],
) -> None:
    client, repository, _ = api_context
    job = reconstruction_job(status=JobStatus.FAILED, output_artifact_id=uuid4())
    repository.initiation = ReconstructionInitiation(reconstruction=job)
    response = await client.get(f"/api/v1/jobs/{job.job.id}")
    await client.aclose()
    assert response.status_code == 200
    assert response.json()["outputArtifactId"] == str(job.output_artifact_id)
    assert response.json()["errorCode"] == "provider_failed"


def processor(
    repository: FakeReconstructionRepository,
    blob: FakeBlobStorage,
    provider: FakeProvider,
    queue: FakeGenerationQueue,
    downloader: ModelDownloader | None = None,
) -> GenerationJobProcessor:
    return GenerationJobProcessor(
        repository=repository,
        blob_storage=blob,
        provider=provider,
        generation_queue=queue,
        source_max_size_bytes=1024,
        model_max_size_bytes=1024,
        source_sas_lifetime=timedelta(minutes=5),
        poll_interval=timedelta(seconds=10),
        max_runtime=timedelta(minutes=20),
        http_timeout_seconds=5,
        model_downloader=downloader,
    )


@pytest.mark.asyncio
async def test_source_sha_mismatch_prevents_paid_submission() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job()
    blob = FakeBlobStorage(b"\x89PNG\r\n\x1a\nchanged")
    provider = FakeProvider()
    await processor(repository, blob, provider, FakeGenerationQueue()).process(
        job_id=repository.worker_job.reconstruction.job.id,
        owner_id=OWNER_ID,
    )
    assert provider.submissions == 0
    assert repository.terminal_states == [("failed", "source_image_validation_failed")]


@pytest.mark.asyncio
async def test_source_mime_signature_mismatch_prevents_paid_submission() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(mime_type="image/jpeg")
    provider = FakeProvider()
    await processor(repository, FakeBlobStorage(), provider, FakeGenerationQueue()).process(
        job_id=repository.worker_job.reconstruction.job.id,
        owner_id=OWNER_ID,
    )
    assert provider.submissions == 0
    assert repository.terminal_states == [("failed", "source_image_validation_failed")]


@pytest.mark.asyncio
async def test_missing_source_blob_prevents_paid_submission() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job()
    blob = FakeBlobStorage()
    blob.download_error = BlobNotFoundError("missing")
    provider = FakeProvider()
    await processor(repository, blob, provider, FakeGenerationQueue()).process(
        job_id=repository.worker_job.reconstruction.job.id,
        owner_id=OWNER_ID,
    )
    assert provider.submissions == 0
    assert repository.terminal_states == [("failed", "source_image_validation_failed")]


@pytest.mark.asyncio
async def test_temporary_source_blob_failure_is_rescheduled() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job()
    blob = FakeBlobStorage()
    blob.download_error = BlobStorageError("temporary")
    queue = FakeGenerationQueue()
    await processor(repository, blob, FakeProvider(), queue).process(
        job_id=repository.worker_job.reconstruction.job.id,
        owner_id=OWNER_ID,
    )
    assert queue.scheduled == [repository.worker_job.reconstruction.job.id]
    assert repository.terminal_states == []


@pytest.mark.asyncio
async def test_fresh_unconfirmed_provider_submission_is_rescheduled_without_resubmission() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(status=JobStatus.RUNNING)
    provider = FakeProvider()
    queue = FakeGenerationQueue()
    await processor(repository, FakeBlobStorage(), provider, queue).process(
        job_id=repository.worker_job.reconstruction.job.id,
        owner_id=OWNER_ID,
    )
    assert provider.submissions == 0
    assert queue.scheduled == [repository.worker_job.reconstruction.job.id]
    assert repository.terminal_states == []


@pytest.mark.asyncio
async def test_stale_unconfirmed_provider_submission_fails_without_resubmission() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(
        status=JobStatus.RUNNING,
        updated_at=datetime.now(UTC) - timedelta(seconds=21),
    )
    provider = FakeProvider()
    await processor(repository, FakeBlobStorage(), provider, FakeGenerationQueue()).process(
        job_id=repository.worker_job.reconstruction.job.id,
        owner_id=OWNER_ID,
    )
    assert provider.submissions == 0
    assert repository.terminal_states == [("failed", "provider_submission_unconfirmed")]


@pytest.mark.asyncio
async def test_valid_source_submits_once_and_later_queue_delivery_only_polls() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job()
    blob = FakeBlobStorage()
    provider = FakeProvider()
    queue = FakeGenerationQueue()
    current = processor(repository, blob, provider, queue)
    await current.process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert provider.submissions == 1
    assert repository.persisted_provider_ids == ["fal-request"]
    assert len(queue.scheduled) == 1

    repository.worker_job = worker_job(provider_job_id="fal-request")
    await current.process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert provider.submissions == 1
    assert len(queue.scheduled) == 2


@pytest.mark.asyncio
async def test_provider_success_stores_one_bounded_canonical_model() -> None:
    async def download(_: ReconstructionOutput, __: int, ___: int) -> bytes:
        return glb_bytes()

    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(provider_job_id="fal-request")
    blob = FakeBlobStorage()
    await processor(
        repository,
        blob,
        FakeProvider(ReconstructionState.SUCCEEDED),
        FakeGenerationQueue(),
        download,
    ).process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert repository.created_outputs == 1
    assert repository.succeeded
    assert blob.uploaded[0][0].endswith("/model.glb")
    assert blob.uploaded[0][2] == "model/gltf-binary"


@pytest.mark.asyncio
async def test_existing_matching_canonical_model_is_reused() -> None:
    async def download(_: ReconstructionOutput, __: int, ___: int) -> bytes:
        return glb_bytes()

    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(provider_job_id="fal-request")
    blob = FakeBlobStorage()
    blob.upload_result = False
    blob.existing_properties = StoredBlobProperties(
        size_bytes=len(glb_bytes()),
        content_type="model/gltf-binary",
        sha256=hashlib.sha256(glb_bytes()).hexdigest(),
    )
    await processor(
        repository,
        blob,
        FakeProvider(ReconstructionState.SUCCEEDED),
        FakeGenerationQueue(),
        download,
    ).process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert repository.created_outputs == 1
    assert repository.succeeded


@pytest.mark.asyncio
async def test_conflicting_existing_canonical_model_fails_safely() -> None:
    async def download(_: ReconstructionOutput, __: int, ___: int) -> bytes:
        return glb_bytes()

    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(provider_job_id="fal-request")
    blob = FakeBlobStorage()
    blob.upload_result = False
    blob.existing_properties = StoredBlobProperties(
        size_bytes=len(glb_bytes()) + 1,
        content_type="model/gltf-binary",
        sha256=hashlib.sha256(glb_bytes()).hexdigest(),
    )
    await processor(
        repository,
        blob,
        FakeProvider(ReconstructionState.SUCCEEDED),
        FakeGenerationQueue(),
        download,
    ).process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert repository.created_outputs == 0
    assert repository.succeeded is False
    assert repository.terminal_states == [("failed", "canonical_model_conflict")]


@pytest.mark.asyncio
async def test_provider_result_network_failure_is_rescheduled() -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(provider_job_id="fal-request")
    provider = FakeProvider(ReconstructionState.SUCCEEDED)
    provider.result_error = ApplicationError(
        code="reconstruction_provider_unavailable",
        message="temporary",
    )
    queue = FakeGenerationQueue()
    await processor(repository, FakeBlobStorage(), provider, queue).process(
        job_id=repository.worker_job.reconstruction.job.id,
        owner_id=OWNER_ID,
    )
    assert queue.scheduled == [repository.worker_job.reconstruction.job.id]
    assert repository.terminal_states == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [b"glTF", glb_bytes(version=1), glb_bytes(declared_length=16), b"invalid"],
)
async def test_invalid_glb_fails_terminally(content: bytes) -> None:
    async def download(_: ReconstructionOutput, __: int, ___: int) -> bytes:
        return content

    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(provider_job_id="fal-request")
    await processor(
        repository,
        FakeBlobStorage(),
        FakeProvider(ReconstructionState.SUCCEEDED),
        FakeGenerationQueue(),
        download,
    ).process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert repository.terminal_states == [("failed", "provider_result_invalid")]


@pytest.mark.asyncio
async def test_oversized_provider_result_fails_terminally() -> None:
    async def download(_: ReconstructionOutput, __: int, ___: int) -> bytes:
        raise ApplicationError(code="reconstruction_model_invalid", message="too large")

    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(provider_job_id="fal-request")
    await processor(
        repository,
        FakeBlobStorage(),
        FakeProvider(ReconstructionState.SUCCEEDED),
        FakeGenerationQueue(),
        download,
    ).process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert repository.terminal_states == [("failed", "provider_result_invalid")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_status", "error_code"),
    [
        (ReconstructionState.FAILED, "failed", "provider_failed"),
        (ReconstructionState.CANCELED, "canceled", None),
    ],
)
async def test_terminal_provider_states_are_recorded(
    state: ReconstructionState,
    expected_status: str,
    error_code: str | None,
) -> None:
    repository = FakeReconstructionRepository()
    repository.worker_job = worker_job(provider_job_id="fal-request")
    await processor(
        repository,
        FakeBlobStorage(),
        FakeProvider(state),
        FakeGenerationQueue(),
    ).process(job_id=repository.worker_job.reconstruction.job.id, owner_id=OWNER_ID)
    assert repository.terminal_states == [(expected_status, error_code)]


@pytest.mark.parametrize("body", [[], [b"not json"], [b'{"jobId":"not-a-uuid"}']])
def test_malformed_generation_message_is_rejected(body: list[bytes]) -> None:
    assert _parse_message(body) is None
