from typing import Protocol

from app.providers.reconstruction.models import (
    ReconstructionOutput,
    ReconstructionRequest,
    ReconstructionStatus,
    ReconstructionSubmission,
)


class ReconstructionProvider(Protocol):
    """Provider-neutral contract; provider response schemas stop at its implementation."""

    async def submit(self, request: ReconstructionRequest) -> ReconstructionSubmission: ...

    async def get_status(self, provider_job_id: str) -> ReconstructionStatus: ...

    async def get_result(self, provider_job_id: str) -> ReconstructionOutput: ...

    async def cancel(self, provider_job_id: str) -> ReconstructionStatus: ...
