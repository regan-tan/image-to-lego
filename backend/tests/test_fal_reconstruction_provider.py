import json
from uuid import uuid4

import httpx
import pytest

from app.core.errors import ApplicationError
from app.providers.reconstruction.fal import FalReconstructionProvider
from app.providers.reconstruction.models import ReconstructionRequest, ReconstructionState


def provider(handler: httpx.MockTransport) -> FalReconstructionProvider:
    return FalReconstructionProvider(api_key="test-key", timeout_seconds=30, transport=handler)


@pytest.mark.asyncio
async def test_submit_uses_trellis_queue_url_auth_and_image_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://queue.fal.run/fal-ai/trellis"
        assert request.headers["Authorization"] == "Key test-key"
        assert json.loads(request.content) == {
            "image_url": "https://storage.example.test/source?sig=x"
        }
        return httpx.Response(200, json={"request_id": "request-123"})

    submission = await provider(httpx.MockTransport(handler)).submit(
        ReconstructionRequest(
            input_artifact_id=uuid4(),
            model="fal-ai/trellis",
            source_url="https://storage.example.test/source?sig=x",
        )
    )
    assert submission.provider_job_id == "request-123"
    assert submission.state is ReconstructionState.QUEUED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_status", "expected_state"),
    [
        ("IN_QUEUE", ReconstructionState.QUEUED),
        ("IN_PROGRESS", ReconstructionState.RUNNING),
        ("COMPLETED", ReconstructionState.SUCCEEDED),
    ],
)
async def test_status_maps_fal_queue_states(
    raw_status: str,
    expected_state: ReconstructionState,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/fal-ai/trellis/requests/request-123/status"
        return httpx.Response(200, json={"status": raw_status})

    status = await provider(httpx.MockTransport(handler)).get_status("request-123")
    assert status.state is expected_state


@pytest.mark.asyncio
async def test_result_parses_model_mesh() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model_mesh": {
                    "url": "https://v3b.fal.media/files/model.glb",
                    "content_type": "application/octet-stream",
                    "file_name": "model.glb",
                    "file_size": 12,
                }
            },
        )

    result = await provider(httpx.MockTransport(handler)).get_result("request-123")
    assert result.url == "https://v3b.fal.media/files/model.glb"
    assert result.mime_type == "application/octet-stream"
    assert result.file_name == "model.glb"
    assert result.size_bytes == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"request_id": ""}, {"status": "UNEXPECTED"}, {"model_mesh": {"url": 1}}],
)
async def test_malformed_fal_payload_is_rejected(payload: dict[str, object]) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = provider(httpx.MockTransport(handler))
    with pytest.raises(ApplicationError, match="unexpected response"):
        if "request_id" in payload:
            await client.submit(
                ReconstructionRequest(
                    input_artifact_id=uuid4(),
                    model="fal-ai/trellis",
                )
            )
        elif "status" in payload:
            await client.get_status("request-123")
        else:
            await client.get_result("request-123")


@pytest.mark.asyncio
async def test_untrusted_result_host_is_rejected() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model_mesh": {"url": "https://example.test/model.glb"}})

    with pytest.raises(ApplicationError, match="unexpected response"):
        await provider(httpx.MockTransport(handler)).get_result("request-123")
