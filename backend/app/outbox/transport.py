"""Maps persisted intents to the existing versioned Service Bus messages."""

from app.outbox.dispatcher import (
    PublicationNotAttemptedError,
    SubmissionMessageTransport,
    SubmissionOutboxClaim,
)
from app.providers.conversion_queue import CONVERSION_MESSAGE_VERSION, ConversionQueue
from app.providers.generation_queue import GENERATION_MESSAGE_VERSION, GenerationQueue


class AzureServiceBusSubmissionTransport(SubmissionMessageTransport):
    def __init__(
        self, generation_queue: GenerationQueue, conversion_queue: ConversionQueue
    ) -> None:
        self._generation_queue = generation_queue
        self._conversion_queue = conversion_queue

    async def publish(self, claim: SubmissionOutboxClaim) -> None:
        if claim.message_type == "reconstruction_job":
            if claim.schema_version != GENERATION_MESSAGE_VERSION:
                raise PublicationNotAttemptedError("Unsupported reconstruction message version.")
            await self._generation_queue.enqueue(job_id=claim.job_id, owner_id=claim.owner_id)
            return
        if claim.message_type == "conversion_job":
            if claim.schema_version != CONVERSION_MESSAGE_VERSION:
                raise PublicationNotAttemptedError("Unsupported conversion message version.")
            await self._conversion_queue.enqueue(job_id=claim.job_id, owner_id=claim.owner_id)
            return
        raise PublicationNotAttemptedError("Unsupported submission outbox message type.")
