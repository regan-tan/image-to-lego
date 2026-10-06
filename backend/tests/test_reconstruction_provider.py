from uuid import UUID

import pytest

from app.core.errors import ApplicationError
from app.providers.reconstruction import (
    FakeReconstructionProvider,
    ReconstructionProvider,
    ReconstructionRequest,
    ReconstructionState,
)


def accepts_provider_contract(provider: ReconstructionProvider) -> ReconstructionProvider:
    return provider


@pytest.mark.asyncio
async def test_fake_provider_submit_status_and_cancel_contract() -> None:
    provider = accepts_provider_contract(FakeReconstructionProvider())
    request = ReconstructionRequest(
        input_artifact_id=UUID("eb4d4208-4c79-4bb4-a636-329a37ee5c24"),
        model="test-model",
    )
    first_submission = await provider.submit(request)
    second_submission = await provider.submit(request)
    assert first_submission == second_submission
    assert first_submission.state is ReconstructionState.QUEUED
    assert (await provider.get_status(first_submission.provider_job_id)).state is (
        ReconstructionState.QUEUED
    )
    assert (await provider.cancel(first_submission.provider_job_id)).state is (
        ReconstructionState.CANCELED
    )


@pytest.mark.asyncio
async def test_fake_provider_rejects_unknown_jobs() -> None:
    provider = FakeReconstructionProvider()
    with pytest.raises(ApplicationError, match="does not exist"):
        await provider.get_status("missing")
