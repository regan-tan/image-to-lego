import asyncio
import hashlib
import json
import logging
from collections.abc import Iterable
from uuid import UUID, uuid4

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.conversion import Axis, ConversionError, ConversionSettings, LegoModel, convert_glb
from app.conversion.core import MAX_INPUT_BYTES
from app.core.config import Settings, get_settings
from app.domain.artifacts import ArtifactStatus
from app.domain.jobs import JobStatus, WorkerConversionJob
from app.providers.blob_storage import (
    AzureBlobStorage,
    BlobNotFoundError,
    BlobStorage,
    BlobStorageError,
)
from app.repositories.conversion import ConversionRepository
from app.repositories.sqlalchemy_conversion import SqlAlchemyConversionRepository

logger = logging.getLogger(__name__)

LEGO_MODEL_MIME_TYPE = "application/json"
_TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED})


class ConversionJobProcessor:
    def __init__(self, *, repository: ConversionRepository, blob_storage: BlobStorage) -> None:
        self._repository = repository
        self._blob_storage = blob_storage

    async def process(self, *, job_id: UUID, owner_id: UUID) -> None:
        worker_job = await self._repository.get_for_worker(job_id=job_id, owner_id=owner_id)
        if worker_job is None or worker_job.conversion.job.status in _TERMINAL_JOB_STATUSES:
            return
        if worker_job.conversion.output_artifact_id is not None:
            await self._repository.mark_succeeded(job_id=job_id, owner_id=owner_id)
            return
        if (
            worker_job.conversion.job.status is JobStatus.QUEUED
            and not await self._repository.claim(job_id=job_id, owner_id=owner_id)
        ):
            return

        source_content = await self._download_verified_source(worker_job)
        if source_content is None:
            return
        try:
            model = convert_glb(
                source_content,
                ConversionSettings(
                    target_parts=worker_job.conversion.target_parts,
                    up_axis=Axis(worker_job.conversion.up_axis),
                ),
            )
        except ConversionError:
            await self._fail(
                worker_job,
                code="conversion_failed",
                message="The reconstructed model could not be converted to LEGO.",
            )
            return

        content = serialize_lego_model(model)
        sha256 = hashlib.sha256(content).hexdigest()
        blob_name = (
            f"projects/{worker_job.conversion.job.project_id}/conversions/"
            f"{worker_job.conversion.job.id}/lego-model.json"
        )
        try:
            created = await self._blob_storage.upload_generated_artifact(
                blob_name=blob_name,
                content=content,
                mime_type=LEGO_MODEL_MIME_TYPE,
                sha256=sha256,
            )
        except BlobStorageError:
            await self._fail(
                worker_job,
                code="conversion_output_storage_failed",
                message="The LEGO model could not be stored safely.",
            )
            return
        if not created:
            try:
                properties = await self._blob_storage.get_properties(blob_name=blob_name)
            except BlobStorageError:
                await self._fail(
                    worker_job,
                    code="conversion_output_storage_failed",
                    message="The LEGO model could not be stored safely.",
                )
                return
            if (
                properties is None
                or properties.size_bytes != len(content)
                or properties.content_type != LEGO_MODEL_MIME_TYPE
                or properties.sha256 != sha256
            ):
                await self._fail(
                    worker_job,
                    code="canonical_lego_model_conflict",
                    message="The LEGO model could not be stored safely.",
                )
                return

        await self._repository.create_output_artifact(
            job_id=job_id,
            owner_id=owner_id,
            artifact_id=uuid4(),
            blob_name=blob_name,
            mime_type=LEGO_MODEL_MIME_TYPE,
            size_bytes=len(content),
            sha256=sha256,
        )
        await self._repository.mark_succeeded(job_id=job_id, owner_id=owner_id)

    async def _download_verified_source(self, worker_job: WorkerConversionJob) -> bytes | None:
        source = worker_job.source_artifact
        if source.kind != "reconstructed_model" or source.status is not ArtifactStatus.READY:
            await self._fail(
                worker_job,
                code="conversion_source_not_ready",
                message="The reconstructed model is not ready for conversion.",
            )
            return None
        try:
            content = await self._blob_storage.download_bounded(
                blob_name=source.blob_name,
                max_bytes=MAX_INPUT_BYTES,
            )
        except BlobNotFoundError:
            await self._fail(
                worker_job,
                code="conversion_source_unavailable",
                message="The reconstructed model is no longer available.",
            )
            return None
        except BlobStorageError:
            await self._fail(
                worker_job,
                code="conversion_source_unavailable",
                message="The reconstructed model could not be read.",
            )
            return None
        if not content or hashlib.sha256(content).hexdigest() != source.sha256:
            await self._fail(
                worker_job,
                code="conversion_source_integrity_failed",
                message="The reconstructed model failed an integrity check.",
            )
            return None
        return content

    async def _fail(self, worker_job: WorkerConversionJob, *, code: str, message: str) -> None:
        await self._repository.mark_failed(
            job_id=worker_job.conversion.job.id,
            owner_id=worker_job.owner_id,
            error_code=code,
            error_message=message,
        )


def serialize_lego_model(model: LegoModel) -> bytes:
    payload = {
        "partCount": model.part_count,
        "dimensions": {
            "widthStuds": model.dimensions.width_studs,
            "depthStuds": model.dimensions.depth_studs,
            "heightBricks": model.dimensions.height_bricks,
            "widthMm": model.dimensions.width_mm,
            "depthMm": model.dimensions.depth_mm,
            "heightMm": model.dimensions.height_mm,
        },
        "metadata": {
            "algorithmVersion": model.metadata.algorithm_version,
            "sourceSha256": model.metadata.source_sha256,
            "targetParts": model.metadata.target_parts,
            "occupiedCellCount": model.metadata.occupied_cell_count,
            "gridSize": {
                "widthStuds": model.metadata.grid_size.width_studs,
                "depthStuds": model.metadata.grid_size.depth_studs,
                "heightBricks": model.metadata.grid_size.height_bricks,
            },
            "candidateCount": model.metadata.candidate_count,
            "occupancyMode": model.metadata.occupancy_mode,
        },
        "placements": [
            {
                "brickType": placement.brick_type.name,
                "dimensions": {
                    "lengthStuds": placement.brick_type.dimensions.length_studs,
                    "widthStuds": placement.brick_type.dimensions.width_studs,
                    "heightBricks": placement.brick_type.dimensions.height_bricks,
                },
                "position": {
                    "x": placement.position.x,
                    "y": placement.position.y,
                    "z": placement.position.z,
                },
                "orientationDegrees": placement.orientation_degrees,
                "color": placement.color,
            }
            for placement in model.placements
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return serialized.encode("utf-8")


async def run_worker(settings: Settings) -> None:
    if not (
        settings.database_url
        and settings.azure_storage_account_url
        and settings.azure_storage_container
        and settings.azure_service_bus_namespace
        and settings.azure_service_bus_queue
    ):
        raise RuntimeError("Conversion worker configuration is incomplete.")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    credential = DefaultAzureCredential()
    blob_storage = AzureBlobStorage(
        account_url=settings.azure_storage_account_url,
        container_name=settings.azure_storage_container,
        credential=credential,
    )
    service_bus = ServiceBusClient(
        fully_qualified_namespace=settings.azure_service_bus_namespace,
        credential=credential,
    )
    try:
        async with service_bus.get_queue_receiver(
            queue_name=settings.azure_service_bus_queue,
            max_wait_time=5,
        ) as receiver:
            while True:
                messages = await receiver.receive_messages(max_message_count=1, max_wait_time=5)
                for message in messages:
                    parsed = _parse_message(message.body)
                    if parsed is None:
                        await receiver.dead_letter_message(
                            message,
                            reason="malformed_conversion_message",
                            error_description=(
                                "Conversion messages require valid jobId and ownerId UUIDs."
                            ),
                        )
                        continue
                    job_id, owner_id = parsed
                    async with session_factory() as session:
                        processor = ConversionJobProcessor(
                            repository=SqlAlchemyConversionRepository(session),
                            blob_storage=blob_storage,
                        )
                        try:
                            await processor.process(job_id=job_id, owner_id=owner_id)
                        except Exception:
                            logger.exception(
                                "Conversion message processing failed for job %s",
                                job_id,
                            )
                            await receiver.abandon_message(message)
                        else:
                            await receiver.complete_message(message)
    finally:
        await service_bus.close()
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
