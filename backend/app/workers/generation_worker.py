import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.errors import ApplicationError
from app.domain.artifacts import ArtifactStatus
from app.domain.jobs import JobStatus, WorkerReconstructionJob
from app.providers.blob_storage import (
    AzureBlobStorage,
    BlobNotFoundError,
    BlobStorage,
    BlobStorageError,
)
from app.providers.generation_queue import AzureServiceBusGenerationQueue, GenerationQueue
from app.providers.reconstruction import (
    FalReconstructionProvider,
    ReconstructionOutput,
    ReconstructionProvider,
    ReconstructionRequest,
    ReconstructionState,
)
from app.repositories.reconstruction import ReconstructionRepository
from app.repositories.sqlalchemy_reconstruction import SqlAlchemyReconstructionRepository

logger = logging.getLogger(__name__)

SUPPORTED_MODEL_MIME_TYPE = "model/gltf-binary"
MODEL_EXTENSION = "glb"
FAL_RESULT_HOST_SUFFIX = ".fal.media"
SUBMISSION_CLAIM_TIMEOUT_MULTIPLIER = 2
ModelDownloader = Callable[[ReconstructionOutput, int, int], Awaitable[bytes]]


class GenerationJobProcessor:
    """Runs one queue-delivered reconstruction job without holding the message while polling."""

    def __init__(
        self,
        *,
        repository: ReconstructionRepository,
        blob_storage: BlobStorage,
        provider: ReconstructionProvider,
        generation_queue: GenerationQueue,
        source_max_size_bytes: int,
        model_max_size_bytes: int,
        source_sas_lifetime: timedelta,
        poll_interval: timedelta,
        max_runtime: timedelta,
        http_timeout_seconds: int,
        model_downloader: ModelDownloader | None = None,
    ) -> None:
        self._repository = repository
        self._blob_storage = blob_storage
        self._provider = provider
        self._generation_queue = generation_queue
        self._source_max_size_bytes = source_max_size_bytes
        self._model_max_size_bytes = model_max_size_bytes
        self._source_sas_lifetime = source_sas_lifetime
        self._poll_interval = poll_interval
        self._max_runtime = max_runtime
        self._http_timeout_seconds = http_timeout_seconds
        self._model_downloader = model_downloader or download_fal_model

    async def process(self, *, job_id: UUID, owner_id: UUID) -> None:
        worker_job = await self._repository.get_for_worker(job_id=job_id, owner_id=owner_id)
        if worker_job is None or worker_job.reconstruction.job.status in _TERMINAL_JOB_STATUSES:
            return
        if _has_exceeded_runtime(worker_job, self._max_runtime):
            await self._repository.mark_terminal(
                job_id=job_id,
                owner_id=owner_id,
                status=JobStatus.FAILED.value,
                error_code="reconstruction_timed_out",
                error_message="The reconstruction exceeded the maximum processing time.",
            )
            return

        provider_job_id = worker_job.reconstruction.job.provider_job_id
        if provider_job_id is None:
            if worker_job.reconstruction.job.status is JobStatus.RUNNING:
                await self._handle_unconfirmed_submission(worker_job)
                return
            await self._submit_once(worker_job)
            return

        await self._observe_provider(worker_job, provider_job_id)

    async def _handle_unconfirmed_submission(self, worker_job: WorkerReconstructionJob) -> None:
        """Resolve the crash window after claiming a paid provider submission.

        A running job without a provider request ID may have reached fal before the
        ID was persisted. It is never safe to submit it again.
        """
        claim_age = datetime.now(UTC) - worker_job.reconstruction.job.updated_at
        claim_timeout = max(
            self._poll_interval * SUBMISSION_CLAIM_TIMEOUT_MULTIPLIER,
            timedelta(seconds=self._http_timeout_seconds * SUBMISSION_CLAIM_TIMEOUT_MULTIPLIER),
        )
        if claim_age <= claim_timeout:
            await self._schedule_check(worker_job)
            return
        await self._repository.mark_terminal(
            job_id=worker_job.reconstruction.job.id,
            owner_id=worker_job.owner_id,
            status=JobStatus.FAILED.value,
            error_code="provider_submission_unconfirmed",
            error_message="The reconstruction provider request could not be confirmed.",
        )

    async def _submit_once(self, worker_job: WorkerReconstructionJob) -> None:
        try:
            source_error = await self._validate_source(worker_job)
        except BlobStorageError:
            await self._schedule_check(worker_job)
            return
        if source_error is not None:
            await self._repository.mark_terminal(
                job_id=worker_job.reconstruction.job.id,
                owner_id=worker_job.owner_id,
                status=JobStatus.FAILED.value,
                error_code="source_image_validation_failed",
                error_message=source_error,
            )
            return

        try:
            source_url = await self._blob_storage.create_read_url(
                blob_name=worker_job.source_artifact.blob_name,
                expires_at=datetime.now(UTC) + self._source_sas_lifetime,
            )
        except BlobStorageError:
            # No provider request has been submitted yet, so delay rather than consume deliveries.
            await self._schedule_check(worker_job)
            return

        claimed = await self._repository.claim_provider_submission(
            job_id=worker_job.reconstruction.job.id,
            owner_id=worker_job.owner_id,
        )
        if not claimed:
            return

        try:
            submission = await self._provider.submit(
                ReconstructionRequest(
                    input_artifact_id=worker_job.source_artifact.id,
                    source_url=source_url,
                    model="fal-ai/trellis",
                )
            )
        except ApplicationError as error:
            # An ambiguous failed submit is not retried, because it could duplicate paid work.
            await self._repository.mark_terminal(
                job_id=worker_job.reconstruction.job.id,
                owner_id=worker_job.owner_id,
                status=JobStatus.FAILED.value,
                error_code="provider_submission_unconfirmed",
                error_message="The reconstruction provider could not confirm the request.",
            )
            logger.info("Generation submission was not confirmed: %s", error.code)
            return

        await self._repository.persist_provider_job_id(
            job_id=worker_job.reconstruction.job.id,
            owner_id=worker_job.owner_id,
            provider_job_id=submission.provider_job_id,
        )
        await self._schedule_check(worker_job)

    async def _observe_provider(
        self,
        worker_job: WorkerReconstructionJob,
        provider_job_id: str,
    ) -> None:
        try:
            provider_status = await self._provider.get_status(provider_job_id)
        except ApplicationError as error:
            if _is_retryable_external_error(error):
                await self._schedule_check(worker_job)
                return
            await self._mark_invalid_result(worker_job, error)
            return
        if provider_status.state in {ReconstructionState.QUEUED, ReconstructionState.RUNNING}:
            await self._schedule_check(worker_job)
            return
        if provider_status.state is ReconstructionState.FAILED:
            await self._repository.mark_terminal(
                job_id=worker_job.reconstruction.job.id,
                owner_id=worker_job.owner_id,
                status=JobStatus.FAILED.value,
                error_code="provider_failed",
                error_message="The reconstruction provider could not generate a model.",
            )
            return
        if provider_status.state is ReconstructionState.CANCELED:
            await self._repository.mark_terminal(
                job_id=worker_job.reconstruction.job.id,
                owner_id=worker_job.owner_id,
                status=JobStatus.CANCELED.value,
            )
            return
        await self._store_completed_model(worker_job, provider_job_id)

    async def _store_completed_model(
        self,
        worker_job: WorkerReconstructionJob,
        provider_job_id: str,
    ) -> None:
        if worker_job.reconstruction.output_artifact_id is not None:
            await self._repository.mark_succeeded(
                job_id=worker_job.reconstruction.job.id,
                owner_id=worker_job.owner_id,
            )
            return
        try:
            output = await self._provider.get_result(provider_job_id)
            content = await self._model_downloader(
                output,
                self._model_max_size_bytes,
                self._http_timeout_seconds,
            )
            mime_type, extension = _validate_model(content)
        except ApplicationError as error:
            if _is_retryable_external_error(error):
                await self._schedule_check(worker_job)
                return
            await self._mark_invalid_result(worker_job, error)
            return

        sha256 = hashlib.sha256(content).hexdigest()
        blob_name = (
            f"projects/{worker_job.reconstruction.job.project_id}/reconstructions/"
            f"{worker_job.reconstruction.job.id}/model.{extension}"
        )
        try:
            created = await self._blob_storage.upload_generated_artifact(
                blob_name=blob_name,
                content=content,
                mime_type=mime_type,
                sha256=sha256,
            )
        except BlobStorageError:
            await self._schedule_check(worker_job)
            return
        if not created:
            try:
                properties = await self._blob_storage.get_properties(blob_name=blob_name)
            except BlobStorageError:
                await self._schedule_check(worker_job)
                return
            if properties is None:
                await self._schedule_check(worker_job)
                return
            if (
                properties.size_bytes != len(content)
                or properties.content_type != mime_type
                or properties.sha256 != sha256
            ):
                await self._repository.mark_terminal(
                    job_id=worker_job.reconstruction.job.id,
                    owner_id=worker_job.owner_id,
                    status=JobStatus.FAILED.value,
                    error_code="canonical_model_conflict",
                    error_message="The generated model could not be stored safely.",
                )
                return
        await self._repository.create_output_artifact(
            job_id=worker_job.reconstruction.job.id,
            owner_id=worker_job.owner_id,
            artifact_id=uuid4(),
            blob_name=blob_name,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=sha256,
        )
        await self._repository.mark_succeeded(
            job_id=worker_job.reconstruction.job.id,
            owner_id=worker_job.owner_id,
        )

    async def _mark_invalid_result(
        self,
        worker_job: WorkerReconstructionJob,
        error: ApplicationError,
    ) -> None:
        await self._repository.mark_terminal(
            job_id=worker_job.reconstruction.job.id,
            owner_id=worker_job.owner_id,
            status=JobStatus.FAILED.value,
            error_code="provider_result_invalid",
            error_message="The reconstruction provider returned an invalid model.",
        )
        logger.info("Generation result was invalid: %s", error.code)

    async def _validate_source(self, worker_job: WorkerReconstructionJob) -> str | None:
        source = worker_job.source_artifact
        if source.status is not ArtifactStatus.READY:
            return "The source image is not ready for reconstruction."
        try:
            content = await self._blob_storage.download_bounded(
                blob_name=source.blob_name,
                max_bytes=self._source_max_size_bytes,
            )
        except BlobNotFoundError:
            return "The source image is no longer available."
        except BlobStorageError:
            raise
        if not content:
            return "The source image is empty."
        if len(content) > self._source_max_size_bytes:
            return "The source image exceeds the maximum allowed size."
        if hashlib.sha256(content).hexdigest() != source.sha256:
            return "The source image failed an integrity check."
        if not _matches_image_signature(source.mime_type, content):
            return "The source image content does not match its declared type."
        return None

    async def _schedule_check(self, worker_job: WorkerReconstructionJob) -> None:
        await self._generation_queue.schedule(
            job_id=worker_job.reconstruction.job.id,
            owner_id=worker_job.owner_id,
            scheduled_for=datetime.now(UTC) + self._poll_interval,
        )


async def download_fal_model(
    output: ReconstructionOutput,
    max_bytes: int,
    timeout_seconds: int,
) -> bytes:
    parsed = urlparse(output.url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not (parsed.hostname == "fal.media" or parsed.hostname.endswith(FAL_RESULT_HOST_SUFFIX))
    ):
        raise _invalid_model()
    timeout = httpx.Timeout(timeout_seconds)
    try:
        async with (
            httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client,
            client.stream("GET", output.url) as response,
        ):
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > max_bytes:
                raise _invalid_model()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise _invalid_model()
    except httpx.HTTPError as error:
        raise ApplicationError(
            code="reconstruction_provider_unavailable",
            message="The reconstruction provider is temporarily unavailable.",
        ) from error
    except ValueError as error:
        raise _invalid_model() from error
    if not content:
        raise _invalid_model()
    return bytes(content)


def _matches_image_signature(mime_type: str, content: bytes) -> bool:
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def _validate_model(content: bytes) -> tuple[str, str]:
    if len(content) < 12 or content[:4] != b"glTF":
        raise _invalid_model()
    version = int.from_bytes(content[4:8], byteorder="little")
    declared_length = int.from_bytes(content[8:12], byteorder="little")
    if version != 2 or declared_length != len(content):
        raise _invalid_model()
    return SUPPORTED_MODEL_MIME_TYPE, MODEL_EXTENSION


def _is_retryable_external_error(error: ApplicationError) -> bool:
    return error.code in {
        "reconstruction_provider_unavailable",
        "reconstruction_result_unavailable",
    }


def _has_exceeded_runtime(worker_job: WorkerReconstructionJob, max_runtime: timedelta) -> bool:
    return datetime.now(UTC) - worker_job.reconstruction.job.created_at > max_runtime


def _invalid_model() -> ApplicationError:
    return ApplicationError(
        code="reconstruction_model_invalid",
        message="The reconstruction provider returned an invalid model.",
    )


_TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED})


async def run_worker(settings: Settings) -> None:
    if not (
        settings.database_url
        and settings.azure_storage_account_url
        and settings.azure_storage_container
        and settings.azure_service_bus_namespace
        and settings.azure_service_bus_generation_queue
        and settings.fal_key
    ):
        raise RuntimeError("Generation worker configuration is incomplete.")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    credential = DefaultAzureCredential()
    blob_storage = AzureBlobStorage(
        account_url=settings.azure_storage_account_url,
        container_name=settings.azure_storage_container,
        credential=credential,
    )
    generation_queue = AzureServiceBusGenerationQueue(
        namespace=settings.azure_service_bus_namespace,
        queue_name=settings.azure_service_bus_generation_queue,
    )
    provider = FalReconstructionProvider(
        api_key=settings.fal_key,
        timeout_seconds=settings.reconstruction_http_timeout_seconds,
    )
    service_bus = ServiceBusClient(
        fully_qualified_namespace=settings.azure_service_bus_namespace,
        credential=credential,
    )
    try:
        async with service_bus.get_queue_receiver(
            queue_name=settings.azure_service_bus_generation_queue,
            max_wait_time=5,
        ) as receiver:
            while True:
                messages = await receiver.receive_messages(max_message_count=1, max_wait_time=5)
                for message in messages:
                    parsed = _parse_message(message.body)
                    if parsed is None:
                        await receiver.dead_letter_message(
                            message,
                            reason="malformed_generation_message",
                            error_description=(
                                "Generation messages require valid jobId and ownerId UUIDs."
                            ),
                        )
                        continue
                    job_id, owner_id = parsed
                    async with session_factory() as session:
                        processor = GenerationJobProcessor(
                            repository=SqlAlchemyReconstructionRepository(session),
                            blob_storage=blob_storage,
                            provider=provider,
                            generation_queue=generation_queue,
                            source_max_size_bytes=settings.upload_max_image_size_bytes,
                            model_max_size_bytes=settings.reconstruction_max_model_size_bytes,
                            source_sas_lifetime=timedelta(
                                minutes=settings.reconstruction_source_sas_lifetime_minutes
                            ),
                            poll_interval=timedelta(
                                seconds=settings.reconstruction_poll_interval_seconds
                            ),
                            max_runtime=timedelta(
                                minutes=settings.reconstruction_max_runtime_minutes
                            ),
                            http_timeout_seconds=settings.reconstruction_http_timeout_seconds,
                        )
                        try:
                            await processor.process(job_id=job_id, owner_id=owner_id)
                        except Exception:
                            logger.exception(
                                "Generation message processing failed for job %s",
                                job_id,
                            )
                            await receiver.abandon_message(message)
                        else:
                            await receiver.complete_message(message)
    finally:
        await service_bus.close()
        await generation_queue.close()
        await blob_storage.close()
        await engine.dispose()


def _parse_message(body: Iterable[bytes]) -> tuple[UUID, UUID] | None:
    try:
        raw = b"".join(body)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        return UUID(str(payload["jobId"])), UUID(str(payload["ownerId"]))
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(get_settings()))


if __name__ == "__main__":
    main()
