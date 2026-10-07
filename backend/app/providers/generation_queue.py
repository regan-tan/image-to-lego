import json
from datetime import datetime
from typing import Protocol
from uuid import UUID

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import ServiceBusError


class GenerationQueueError(Exception):
    """A generation message could not be durably published."""


class GenerationQueue(Protocol):
    async def enqueue(self, *, job_id: UUID, owner_id: UUID) -> None: ...

    async def schedule(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        scheduled_for: datetime,
    ) -> None: ...


class AzureServiceBusGenerationQueue:
    def __init__(
        self,
        *,
        namespace: str,
        queue_name: str,
        credential: AsyncTokenCredential | None = None,
        client: ServiceBusClient | None = None,
    ) -> None:
        self._credential = credential
        if client is None:
            self._credential = credential or DefaultAzureCredential()
            self._client = ServiceBusClient(
                fully_qualified_namespace=namespace,
                credential=self._credential,
            )
        else:
            self._client = client
        self._queue_name = queue_name

    async def enqueue(self, *, job_id: UUID, owner_id: UUID) -> None:
        message = _message(job_id=job_id, owner_id=owner_id)
        try:
            async with self._client.get_queue_sender(queue_name=self._queue_name) as sender:
                await sender.send_messages(message)
        except ServiceBusError as error:
            raise GenerationQueueError("Could not publish the generation job.") from error

    async def schedule(
        self,
        *,
        job_id: UUID,
        owner_id: UUID,
        scheduled_for: datetime,
    ) -> None:
        message = _message(job_id=job_id, owner_id=owner_id)
        try:
            async with self._client.get_queue_sender(queue_name=self._queue_name) as sender:
                await sender.schedule_messages(message, schedule_time_utc=scheduled_for)
        except ServiceBusError as error:
            raise GenerationQueueError("Could not schedule the generation job.") from error

    async def close(self) -> None:
        await self._client.close()
        if self._credential is not None:
            await self._credential.close()


def _message(*, job_id: UUID, owner_id: UUID) -> ServiceBusMessage:
    body = json.dumps({"jobId": str(job_id), "ownerId": str(owner_id)})
    return ServiceBusMessage(body, content_type="application/json")
