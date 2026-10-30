import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from azure.servicebus import ServiceBusReceivedMessage
from azure.servicebus.aio import AutoLockRenewer, ServiceBusReceiver, ServiceBusSession
from azure.servicebus.exceptions import MessageLockLostError, ServiceBusError

MessageProcessor = Callable[[], Awaitable[None]]
AttemptRenewer = Callable[[], Awaitable[bool]]


class LeaveMessageUnsettled(Exception):
    """The worker could not create the durable recovery message needed before settlement."""


async def process_received_message(
    *,
    receiver: ServiceBusReceiver,
    message: ServiceBusReceivedMessage,
    max_processing_duration: timedelta,
    process: MessageProcessor,
    logger: logging.Logger,
    job_description: str,
    renew_attempt: AttemptRenewer | None = None,
    attempt_renewal_interval: timedelta | None = None,
) -> None:
    """Process and settle one message without completing a lost lock."""
    renewal_failed = asyncio.Event()
    attempt_renewal_failed = asyncio.Event()

    async def on_lock_renew_failure(
        _: ServiceBusReceivedMessage | ServiceBusSession,
        error: Exception | None,
    ) -> None:
        logger.warning(
            "Message lock renewal failed for %s; leaving it for redelivery: %s",
            job_description,
            type(error).__name__ if error is not None else "unknown error",
        )
        renewal_failed.set()

    async with AutoLockRenewer(
        max_lock_renewal_duration=max_processing_duration.total_seconds(),
        on_lock_renew_failure=on_lock_renew_failure,
    ) as renewer:
        renewer.register(receiver, message)
        processing_task: asyncio.Future[None] = asyncio.ensure_future(process())
        renewal_failure_task = asyncio.create_task(renewal_failed.wait())
        attempt_failure_task = asyncio.create_task(attempt_renewal_failed.wait())
        attempt_renewal_task = _start_attempt_renewal(
            renew_attempt,
            attempt_renewal_interval,
            attempt_renewal_failed,
            logger,
            job_description,
        )
        try:
            completed, _ = await asyncio.wait(
                (processing_task, renewal_failure_task, attempt_failure_task),
                timeout=max_processing_duration.total_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if renewal_failure_task in completed or attempt_failure_task in completed:
                await _cancel_processing(processing_task)
                return
            if processing_task not in completed:
                logger.error(
                    "Message processing exceeded the configured %s-second limit for %s; retrying.",
                    int(max_processing_duration.total_seconds()),
                    job_description,
                )
                await _cancel_processing(processing_task)
                await _abandon_for_retry(receiver, message, logger, job_description)
                return

            await processing_task
            if renewal_failed.is_set():
                return
            try:
                await receiver.complete_message(message)
            except MessageLockLostError:
                logger.warning(
                    "Message lock was lost before completion for %s; it may be redelivered.",
                    job_description,
                )
            except ServiceBusError:
                logger.exception(
                    "Could not complete message for %s; it may be redelivered.",
                    job_description,
                )
        except LeaveMessageUnsettled:
            logger.exception("Leaving %s unsettled for broker redelivery.", job_description)
        except Exception:
            logger.exception("Message processing failed for %s; retrying.", job_description)
            await _abandon_for_retry(receiver, message, logger, job_description)
        finally:
            await _cancel_processing(processing_task)
            renewal_failure_task.cancel()
            attempt_failure_task.cancel()
            if attempt_renewal_task is not None:
                attempt_renewal_task.cancel()
            await asyncio.gather(
                renewal_failure_task,
                attempt_failure_task,
                *(task for task in (attempt_renewal_task,) if task is not None),
                return_exceptions=True,
            )


def _start_attempt_renewal(
    renew_attempt: AttemptRenewer | None,
    interval: timedelta | None,
    failed: asyncio.Event,
    logger: logging.Logger,
    job_description: str,
) -> asyncio.Task[None] | None:
    if renew_attempt is None or interval is None:
        return None

    async def renew_loop() -> None:
        try:
            while True:
                await asyncio.sleep(interval.total_seconds())
                if not await renew_attempt():
                    logger.warning("Job attempt lease was lost for %s.", job_description)
                    failed.set()
                    return
        except Exception:
            logger.exception("Job attempt lease renewal failed for %s.", job_description)
            failed.set()

    return asyncio.create_task(renew_loop())


async def _cancel_processing(processing_task: asyncio.Future[None]) -> None:
    if not processing_task.done():
        processing_task.cancel()
    await asyncio.gather(processing_task, return_exceptions=True)


async def _abandon_for_retry(
    receiver: ServiceBusReceiver,
    message: ServiceBusReceivedMessage,
    logger: logging.Logger,
    job_description: str,
) -> None:
    try:
        await receiver.abandon_message(message)
    except MessageLockLostError:
        logger.warning(
            "Message lock was lost before retry settlement for %s; it may be redelivered.",
            job_description,
        )
    except ServiceBusError:
        logger.exception(
            "Could not abandon message for %s; it may be redelivered.",
            job_description,
        )
