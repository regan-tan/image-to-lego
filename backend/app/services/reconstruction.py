from app.providers.reconstruction import (
    ReconstructionProvider,
    ReconstructionRequest,
    ReconstructionStatus,
    ReconstructionSubmission,
)


class ReconstructionService:
    def __init__(self, provider: ReconstructionProvider) -> None:
        self._provider = provider

    async def submit(self, request: ReconstructionRequest) -> ReconstructionSubmission:
        return await self._provider.submit(request)

    async def get_status(self, provider_job_id: str) -> ReconstructionStatus:
        return await self._provider.get_status(provider_job_id)

    async def cancel(self, provider_job_id: str) -> ReconstructionStatus:
        return await self._provider.cancel(provider_job_id)

