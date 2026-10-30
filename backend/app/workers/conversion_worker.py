import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import TypeVar, cast
from uuid import UUID, uuid4

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.conversion import (
    BUILDABILITY_ANALYSIS_VERSION,
    INSTRUCTION_PRECEDENCE_ANALYSIS_VERSION,
    VERTICAL_INSERTION_ACCESSIBILITY_VERSION,
    Axis,
    BrickPlacement,
    ConversionError,
    ConversionSettings,
    InstructionStep,
    LegoModel,
    analyze_buildability,
    analyze_instruction_precedence,
    analyze_vertical_insertion_accessibility,
    convert_glb,
    generate_instruction_steps,
    order_placements_for_instructions,
)
from app.conversion.colors import COLORS_BY_ID
from app.conversion.core import MAX_INPUT_BYTES, SURFACE_GRID_V4
from app.conversion.part_catalogue import PART_COLOR_VERIFICATION_VERSION
from app.core.config import Settings, get_settings
from app.domain.artifacts import ArtifactStatus
from app.domain.jobs import JobStatus, WorkerConversionJob
from app.providers.blob_storage import (
    AzureBlobStorage,
    BlobNotFoundError,
    BlobStorage,
    BlobStorageError,
)
from app.providers.conversion_queue import AzureServiceBusConversionQueue, ConversionQueueError
from app.repositories.conversion import ConversionRepository
from app.repositories.sqlalchemy_conversion import SqlAlchemyConversionRepository
from app.workers.message_lock import LeaveMessageUnsettled, process_received_message

logger = logging.getLogger(__name__)

LEGO_MODEL_MIME_TYPE = "application/json"
_TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED})
_ThreadResult = TypeVar("_ThreadResult")


def _bricklink_color_id(color_id: str | None) -> int | None:
    color = COLORS_BY_ID.get(color_id or "")
    return color.bricklink_color_id if color is not None else None


class ConversionExecutionGate:
    """Keeps a cancelled worker from starting another CPU conversion in this process."""

    def __init__(self) -> None:
        self._active: asyncio.Task[object] | None = None

    async def run(self, operation: Callable[[], _ThreadResult]) -> _ThreadResult:
        previous = self._active
        if previous is not None:
            try:
                await asyncio.shield(previous)
            except Exception:
                logger.warning("A previously cancelled conversion thread exited with an error.")
            finally:
                if self._active is previous:
                    self._active = None

        task = asyncio.create_task(asyncio.to_thread(operation))
        self._active = cast(asyncio.Task[object], task)
        task.add_done_callback(_consume_thread_result)
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._active is task:
                self._active = None


def _consume_thread_result(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


class ConversionJobProcessor:
    def __init__(
        self,
        *,
        repository: ConversionRepository,
        blob_storage: BlobStorage,
        execution_gate: ConversionExecutionGate | None = None,
    ) -> None:
        self._repository = repository
        self._blob_storage = blob_storage
        self._execution_gate = execution_gate or ConversionExecutionGate()

    async def process(self, *, job_id: UUID, owner_id: UUID, attempt_id: UUID) -> None:
        worker_job = await self._repository.get_for_worker(job_id=job_id, owner_id=owner_id)
        if worker_job is None or worker_job.conversion.job.status in _TERMINAL_JOB_STATUSES:
            return
        if worker_job.conversion.output_artifact_id is not None:
            await self._repository.mark_succeeded(
                job_id=job_id,
                owner_id=owner_id,
                attempt_id=attempt_id,
            )
            return

        source_content = await self._download_verified_source(worker_job, attempt_id)
        if source_content is None:
            return
        try:
            model = await self._execution_gate.run(
                lambda: convert_glb(
                    source_content,
                    ConversionSettings(
                        target_parts=worker_job.conversion.target_parts,
                        up_axis=Axis(worker_job.conversion.up_axis),
                        algorithm_version=worker_job.conversion.algorithm_version,
                    ),
                )
            )
        except ConversionError:
            await self._fail(
                worker_job,
                attempt_id=attempt_id,
                code="conversion_failed",
                message="The reconstructed model could not be converted to LEGO.",
            )
            return

        content = await self._execution_gate.run(lambda: serialize_lego_model(model))
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
                attempt_id=attempt_id,
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
                    attempt_id=attempt_id,
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
                    attempt_id=attempt_id,
                    code="canonical_lego_model_conflict",
                    message="The LEGO model could not be stored safely.",
                )
                return

        await self._repository.finalize_success(
            job_id=job_id,
            owner_id=owner_id,
            attempt_id=attempt_id,
            artifact_id=uuid4(),
            blob_name=blob_name,
            mime_type=LEGO_MODEL_MIME_TYPE,
            size_bytes=len(content),
            sha256=sha256,
        )

    async def _download_verified_source(
        self,
        worker_job: WorkerConversionJob,
        attempt_id: UUID,
    ) -> bytes | None:
        source = worker_job.source_artifact
        if source.kind != "reconstructed_model" or source.status is not ArtifactStatus.READY:
            await self._fail(
                worker_job,
                attempt_id=attempt_id,
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
                attempt_id=attempt_id,
                code="conversion_source_unavailable",
                message="The reconstructed model is no longer available.",
            )
            return None
        except BlobStorageError:
            await self._fail(
                worker_job,
                attempt_id=attempt_id,
                code="conversion_source_unavailable",
                message="The reconstructed model could not be read.",
            )
            return None
        if not content or hashlib.sha256(content).hexdigest() != source.sha256:
            await self._fail(
                worker_job,
                attempt_id=attempt_id,
                code="conversion_source_integrity_failed",
                message="The reconstructed model failed an integrity check.",
            )
            return None
        return content

    async def _fail(
        self,
        worker_job: WorkerConversionJob,
        *,
        attempt_id: UUID,
        code: str,
        message: str,
    ) -> None:
        await self._repository.mark_failed(
            job_id=worker_job.conversion.job.id,
            owner_id=worker_job.owner_id,
            attempt_id=attempt_id,
            error_code=code,
            error_message=message,
        )


def serialize_lego_model(model: LegoModel) -> bytes:
    ordered_placements = order_placements_for_instructions(model.placements)
    buildability = analyze_buildability(ordered_placements)
    precedence = analyze_instruction_precedence(ordered_placements)
    instruction_steps = generate_instruction_steps(ordered_placements)
    insertion_accessibility = analyze_vertical_insertion_accessibility(
        ordered_placements,
        instruction_steps,
    )
    # surface-grid-v3 uses its historical one-plate grid representation for bricks.
    # Its part IDs remain useful inventory context, but its geometry is not a
    # manufactured-part representation and must not be exported for sourcing.
    catalogue_geometry_verified = model.metadata.algorithm_version == SURFACE_GRID_V4
    metadata: dict[str, object] = {
        "algorithmVersion": model.metadata.algorithm_version,
        "sourceSha256": model.metadata.source_sha256,
        "targetParts": model.metadata.target_parts,
        "occupiedCellCount": model.metadata.occupied_cell_count,
        "gridSize": {
            "widthStuds": model.metadata.grid_size.width_studs,
            "depthStuds": model.metadata.grid_size.depth_studs,
            "heightPlates": model.metadata.grid_size.height_plates,
        },
        "candidateCount": model.metadata.candidate_count,
        "occupancyMode": model.metadata.occupancy_mode,
        "fidelity": {
            "metricsVersion": model.metadata.fidelity.metrics_version,
            "rasterResolution": model.metadata.fidelity.raster_resolution,
            "frontIoU": model.metadata.fidelity.front_iou,
            "sideIoU": model.metadata.fidelity.side_iou,
            "topIoU": model.metadata.fidelity.top_iou,
            "meanIoU": model.metadata.fidelity.mean_iou,
            "targetParts": model.metadata.fidelity.target_parts,
            "actualParts": model.metadata.fidelity.actual_parts,
            "partCountDelta": model.metadata.fidelity.part_count_delta,
            "partCountErrorRatio": model.metadata.fidelity.part_count_error_ratio,
        },
        "buildability": {
            "version": BUILDABILITY_ANALYSIS_VERSION,
            "evaluatedPlacements": buildability.evaluated_placement_count,
            "unevaluatedPlacements": buildability.unevaluated_placement_count,
            "connectionEdges": len(buildability.edges),
            "connectedComponents": buildability.connected_component_count,
            "largestComponentSize": buildability.largest_connected_component_size,
            "largestComponentRatio": buildability.largest_connected_component_ratio,
            "isolatedPlacements": buildability.isolated_placement_count,
            "unsupportedPlacements": buildability.unsupported_placement_count,
        },
        "verticalInsertionAccessibility": {
            "version": VERTICAL_INSERTION_ACCESSIBILITY_VERSION,
            "evaluatedPlacements": insertion_accessibility.evaluated_placement_count,
            "unevaluatedPlacements": insertion_accessibility.unevaluated_placement_count,
            "accessiblePlacements": insertion_accessibility.accessible_placement_count,
            "blockedPlacements": insertion_accessibility.blocked_placement_count,
            "blockedInsertions": [
                {
                    "placementIndex": blocked.placement_index,
                    "blockerPlacementIndices": list(blocked.blocker_placement_indices),
                }
                for blocked in insertion_accessibility.blocked_insertions
            ],
        },
        "instructionPrecedence": {
            "version": INSTRUCTION_PRECEDENCE_ANALYSIS_VERSION,
            "structuralEdges": len(precedence.structural_edges),
            "insertionEdges": len(precedence.insertion_edges),
            "totalPrecedenceEdges": precedence.total_precedence_edge_count,
            "cyclicPlacements": len(precedence.cyclic_placement_indices),
            "cyclicComponents": len(precedence.cyclic_components),
            "cyclicStructuralEdges": precedence.cyclic_structural_edge_count,
            "cyclicInsertionEdges": precedence.cyclic_insertion_edge_count,
            "schedulableEvaluatedPlacements": (precedence.schedulable_evaluated_placement_count),
            "unresolvedVerticalInsertionPlacements": len(
                precedence.unresolved_vertical_insertion_placement_indices
            ),
        },
    }
    if catalogue_geometry_verified:
        metadata["partColorVerificationVersion"] = PART_COLOR_VERIFICATION_VERSION

    # This is deliberately a diagnostic guide, not a claim that the model is
    # physically buildable.  Keep the reasons in the artifact so a client does
    # not have to infer safety from a count alone.
    build_warnings = [
        "Physical assembly is not guaranteed; stability, collision-free motions, and clutch "
        "force are not evaluated."
    ]
    if buildability.unsupported_placement_count:
        build_warnings.append(
            f"{buildability.unsupported_placement_count} placement(s) have no verified "
            "direct support."
        )
    if buildability.connected_component_count > 1:
        build_warnings.append(
            f"The model has {buildability.connected_component_count} evaluated connected "
            "components."
        )
    if insertion_accessibility.blocked_placement_count:
        build_warnings.append(
            f"{insertion_accessibility.blocked_placement_count} placement(s) have a blocked "
            "straight-down insertion path."
        )
    if insertion_accessibility.unevaluated_placement_count:
        build_warnings.append(
            f"{insertion_accessibility.unevaluated_placement_count} placement(s) were not "
            "evaluated for straight-down insertion."
        )
    if precedence.unresolved_vertical_insertion_placement_indices:
        build_warnings.append(
            "Some precedence constraints conflict, so their vertical insertion order is unresolved."
        )

    payload = {
        "partCount": model.part_count,
        "dimensions": {
            "widthStuds": model.dimensions.width_studs,
            "depthStuds": model.dimensions.depth_studs,
            "heightPlates": model.dimensions.height_plates,
            "widthMm": model.dimensions.width_mm,
            "depthMm": model.dimensions.depth_mm,
            "heightMm": model.dimensions.height_mm,
        },
        "metadata": metadata,
        "placements": [
            {
                "brickType": placement.brick_type.catalogue_key,
                "partId": placement.brick_type.part_id,
                "partName": placement.brick_type.name,
                "shape": placement.brick_type.shape,
                "geometryAsset": placement.brick_type.geometry_asset,
                "dimensions": {
                    "lengthStuds": placement.brick_type.dimensions.length_studs,
                    "widthStuds": placement.brick_type.dimensions.width_studs,
                    "heightPlates": placement.brick_type.dimensions.height_plates,
                },
                "position": {
                    "x": placement.position.x,
                    "y": placement.position.y,
                    "z": placement.position.z,
                },
                "orientationDegrees": placement.orientation_degrees,
                "color": placement.color,
                "colorId": placement.color_id,
                "colorName": placement.color_name,
                "colorHex": placement.color_hex,
                "externalIds": {
                    "bricklink": {
                        "partId": placement.brick_type.bricklink_id,
                        "colorId": _bricklink_color_id(placement.color_id),
                    }
                },
                "partColorVerified": catalogue_geometry_verified
                and placement.brick_type.supports_color_id(placement.color_id or ""),
            }
            for placement in ordered_placements
        ],
        "instructionSteps": [
            {
                "stepNumber": step.step_number,
                "placementIndices": list(step.placement_indices),
            }
            for step in instruction_steps
        ],
        "instructionGuide": {
            "version": "build-guide-v2",
            "warnings": build_warnings,
            "steps": [
                {
                    "stepNumber": step.step_number,
                    "placementIndices": list(step.placement_indices),
                    "placements": [
                        {
                            "placementIndex": placement_index,
                            "position": {
                                "x": ordered_placements[placement_index].position.x,
                                "y": ordered_placements[placement_index].position.y,
                                "z": ordered_placements[placement_index].position.z,
                            },
                            "orientationDegrees": (
                                ordered_placements[placement_index].orientation_degrees
                            ),
                            "partId": ordered_placements[placement_index].brick_type.part_id,
                            "colorId": ordered_placements[placement_index].color_id,
                        }
                        for placement_index in step.placement_indices
                    ],
                    "parts": _instruction_step_parts(ordered_placements, step),
                }
                for step in instruction_steps
            ],
        },
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return serialized.encode("utf-8")


def _instruction_step_parts(
    placements: tuple[BrickPlacement, ...],
    step: InstructionStep,
) -> list[dict[str, object]]:
    """Return exact, deterministic part/color quantities for one guide step."""
    quantities: dict[tuple[str, str, str | None], int] = {}
    for placement_index in step.placement_indices:
        placement = placements[placement_index]
        key = (
            placement.brick_type.part_id,
            placement.color,
            placement.color_id,
        )
        quantities[key] = quantities.get(key, 0) + 1

    return [
        {
            "partId": part_id,
            "color": color,
            "colorId": color_id,
            "quantity": quantity,
        }
        for (part_id, color, color_id), quantity in sorted(
            quantities.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
        )
    ]


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
    recovery_queue = AzureServiceBusConversionQueue(
        namespace=settings.azure_service_bus_namespace,
        queue_name=settings.azure_service_bus_queue,
        client=service_bus,
    )
    execution_gate = ConversionExecutionGate()
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
                        repository = SqlAlchemyConversionRepository(session)
                        attempt_id = await repository.acquire_attempt(
                            job_id=job_id,
                            owner_id=owner_id,
                            lease_seconds=settings.worker_job_lease_seconds,
                        )
                        if attempt_id is None:
                            recovery_time = await repository.recovery_time(
                                job_id=job_id,
                                owner_id=owner_id,
                            )
                            if recovery_time is not None:
                                scheduled_recovery_time: datetime = recovery_time

                                async def schedule_recovery(
                                    job_id: UUID = job_id,
                                    owner_id: UUID = owner_id,
                                    recovery_time: datetime = scheduled_recovery_time,
                                ) -> None:
                                    try:
                                        await recovery_queue.schedule(
                                            job_id=job_id,
                                            owner_id=owner_id,
                                            scheduled_for=recovery_time
                                            + timedelta(
                                                seconds=(
                                                    settings.worker_job_lease_recovery_buffer_seconds
                                                )
                                            ),
                                        )
                                    except ConversionQueueError as error:
                                        raise LeaveMessageUnsettled from error

                                await process_received_message(
                                    receiver=receiver,
                                    message=message,
                                    max_processing_duration=timedelta(seconds=60),
                                    process=schedule_recovery,
                                    logger=logger,
                                    job_description=(
                                        f"conversion lease recovery job {job_id}"
                                    ),
                                )
                                continue
                            await process_received_message(
                                receiver=receiver,
                                message=message,
                                max_processing_duration=timedelta(seconds=1),
                                process=_complete_duplicate_delivery,
                                logger=logger,
                                job_description=f"conversion duplicate job {job_id}",
                            )
                            continue
                        owned_attempt_id: UUID = attempt_id
                        processor = ConversionJobProcessor(
                            repository=repository,
                            blob_storage=blob_storage,
                            execution_gate=execution_gate,
                        )

                        async def process_message(
                            processor: ConversionJobProcessor = processor,
                            job_id: UUID = job_id,
                            owner_id: UUID = owner_id,
                            attempt_id: UUID = owned_attempt_id,
                        ) -> None:
                            await processor.process(
                                job_id=job_id,
                                owner_id=owner_id,
                                attempt_id=attempt_id,
                            )

                        async def renew_attempt(
                            job_id: UUID = job_id,
                            owner_id: UUID = owner_id,
                            attempt_id: UUID = owned_attempt_id,
                        ) -> bool:
                            async with session_factory() as lease_session:
                                lease_repository = SqlAlchemyConversionRepository(lease_session)
                                return await lease_repository.renew_attempt(
                                    job_id=job_id,
                                    owner_id=owner_id,
                                    attempt_id=attempt_id,
                                    lease_seconds=settings.worker_job_lease_seconds,
                                )

                        try:
                            await process_received_message(
                                receiver=receiver,
                                message=message,
                                max_processing_duration=timedelta(
                                    seconds=settings.service_bus_max_lock_renewal_seconds
                                ),
                                process=process_message,
                                logger=logger,
                                job_description=f"conversion job {job_id}",
                                renew_attempt=renew_attempt,
                                attempt_renewal_interval=timedelta(
                                    seconds=settings.worker_job_lease_renewal_seconds
                                ),
                            )
                        finally:
                            async with session_factory() as lease_session:
                                await SqlAlchemyConversionRepository(lease_session).release_attempt(
                                    job_id=job_id,
                                    owner_id=owner_id,
                                    attempt_id=owned_attempt_id,
                                )
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


async def _complete_duplicate_delivery() -> None:
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(get_settings()))


if __name__ == "__main__":
    main()
