from uuid import NAMESPACE_URL, uuid5

from app.core.errors import ApplicationError
from app.providers.reconstruction.models import (
    ReconstructionOutput,
    ReconstructionRequest,
    ReconstructionState,
    ReconstructionStatus,
    ReconstructionSubmission,
)


class FakeReconstructionProvider:
    """Deterministic in-memory provider for isolated service and contract tests."""

    def __init__(self) -> None:
        self._states: dict[str, ReconstructionState] = {}

    async def submit(self, request: ReconstructionRequest) -> ReconstructionSubmission:
        provider_job_id = str(uuid5(NAMESPACE_URL, f"{request.input_artifact_id}:{request.model}"))
        self._states[provider_job_id] = ReconstructionState.QUEUED
        return ReconstructionSubmission(
            provider_job_id=provider_job_id,
            state=ReconstructionState.QUEUED,
        )

    async def get_status(self, provider_job_id: str) -> ReconstructionStatus:
        return ReconstructionStatus(
            provider_job_id=provider_job_id,
            state=self._get_state(provider_job_id),
        )

    async def get_result(self, provider_job_id: str) -> ReconstructionOutput:
        self._get_state(provider_job_id)
        raise ApplicationError(
            code="reconstruction_result_unavailable",
            message="The reconstruction result is not available.",
        )

    async def cancel(self, provider_job_id: str) -> ReconstructionStatus:
        self._get_state(provider_job_id)
        self._states[provider_job_id] = ReconstructionState.CANCELED
        return ReconstructionStatus(
            provider_job_id=provider_job_id,
            state=ReconstructionState.CANCELED,
        )

    def _get_state(self, provider_job_id: str) -> ReconstructionState:
        try:
            return self._states[provider_job_id]
        except KeyError as error:
            raise ApplicationError(
                code="reconstruction_job_not_found",
                message="The reconstruction job does not exist.",
            ) from error
