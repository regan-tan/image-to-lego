from collections.abc import Mapping
from urllib.parse import quote, urlparse

import httpx

from app.core.errors import ApplicationError
from app.providers.reconstruction.models import (
    ReconstructionOutput,
    ReconstructionRequest,
    ReconstructionState,
    ReconstructionStatus,
    ReconstructionSubmission,
)

FAL_QUEUE_BASE_URL = "https://queue.fal.run"
FAL_TRELLIS_MODEL = "fal-ai/trellis"
FAL_RESULT_HOST_SUFFIX = ".fal.media"


class FalReconstructionProvider:
    """fal.ai queue adapter. Its response details do not leave this boundary."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def submit(self, request: ReconstructionRequest) -> ReconstructionSubmission:
        payload = await self._request(
            "POST",
            _model_url(),
            json={"image_url": request.source_url},
        )
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise _invalid_response()
        return ReconstructionSubmission(
            provider_job_id=request_id,
            state=ReconstructionState.QUEUED,
        )

    async def get_status(self, provider_job_id: str) -> ReconstructionStatus:
        payload = await self._request("GET", _status_url(provider_job_id))
        return _status_from_payload(provider_job_id, payload)

    async def get_result(self, provider_job_id: str) -> ReconstructionOutput:
        payload = await self._request("GET", _result_url(provider_job_id))
        model_mesh = payload.get("model_mesh")
        if not isinstance(model_mesh, Mapping):
            raise _invalid_response()
        url = model_mesh.get("url")
        if not isinstance(url, str) or not _is_fal_result_url(url):
            raise _invalid_response()
        mime_type = model_mesh.get("content_type")
        file_name = model_mesh.get("file_name")
        size_bytes = model_mesh.get("file_size")
        return ReconstructionOutput(
            url=url,
            mime_type=mime_type if isinstance(mime_type, str) else None,
            file_name=file_name if isinstance(file_name, str) else None,
            size_bytes=size_bytes if isinstance(size_bytes, int) and size_bytes >= 0 else None,
        )

    async def cancel(self, provider_job_id: str) -> ReconstructionStatus:
        payload = await self._request("PUT", _cancel_url(provider_job_id))
        return _status_from_payload(provider_job_id, payload)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, str] | None = None,
    ) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers={"Authorization": f"Key {self._api_key}", "Accept": "application/json"},
                    json=json,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as error:
            raise ApplicationError(
                code="reconstruction_provider_unavailable",
                message="The reconstruction provider is temporarily unavailable.",
            ) from error
        except ValueError as error:
            raise _invalid_response() from error
        if not isinstance(payload, dict):
            raise _invalid_response()
        return payload


def _model_url() -> str:
    return f"{FAL_QUEUE_BASE_URL}/{FAL_TRELLIS_MODEL}"


def _status_url(provider_job_id: str) -> str:
    return f"{_model_url()}/requests/{quote(provider_job_id, safe='')}/status"


def _result_url(provider_job_id: str) -> str:
    return f"{_model_url()}/requests/{quote(provider_job_id, safe='')}"


def _cancel_url(provider_job_id: str) -> str:
    return f"{_result_url(provider_job_id)}/cancel"


def _status_from_payload(
    provider_job_id: str,
    payload: Mapping[str, object],
) -> ReconstructionStatus:
    raw_status = payload.get("status")
    if not isinstance(raw_status, str):
        raise _invalid_response()
    state_by_status = {
        "IN_QUEUE": ReconstructionState.QUEUED,
        "IN_PROGRESS": ReconstructionState.RUNNING,
        "COMPLETED": ReconstructionState.SUCCEEDED,
        "FAILED": ReconstructionState.FAILED,
        "CANCELED": ReconstructionState.CANCELED,
    }
    state = state_by_status.get(raw_status)
    if state is None:
        raise _invalid_response()
    return ReconstructionStatus(provider_job_id=provider_job_id, state=state)


def _is_fal_result_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and (parsed.hostname == "fal.media" or parsed.hostname.endswith(FAL_RESULT_HOST_SUFFIX))
    )


def _invalid_response() -> ApplicationError:
    return ApplicationError(
        code="reconstruction_provider_response_invalid",
        message="The reconstruction provider returned an unexpected response.",
    )
