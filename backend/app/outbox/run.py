"""Bounded command-line runtime for dispatching submission outbox records."""

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum
from typing import Protocol, Self
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.outbox.dispatcher import (
    DispatchRunResult,
    OutboxDispatcherConfig,
    SubmissionOutboxDispatcher,
)
from app.outbox.sqlalchemy import SqlAlchemySubmissionOutboxRepository
from app.outbox.transport import AzureServiceBusSubmissionTransport
from app.providers.conversion_queue import AzureServiceBusConversionQueue
from app.providers.generation_queue import AzureServiceBusGenerationQueue

logger = logging.getLogger(__name__)


class DispatcherExitCode(IntEnum):
    SUCCESS = 0
    RELEASE_BLOCKED = 2
    FAILED = 3
    UNCERTAIN = 4


class Closable(Protocol):
    async def close(self) -> None: ...


class DispatcherAccessValidator(Protocol):
    async def validate_access(self) -> None: ...


class DispatcherRunner(Protocol):
    async def run_once(self, *, dispatcher_id: UUID, max_messages: int) -> DispatchRunResult: ...


@dataclass(slots=True)
class DispatcherRuntime:
    dispatcher: DispatcherRunner
    access_validator: DispatcherAccessValidator
    engine: AsyncEngine | None
    generation_queue: Closable
    conversion_queue: Closable

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        _validate_settings(settings)
        assert settings.database_url is not None
        assert settings.azure_service_bus_namespace is not None
        assert settings.azure_service_bus_generation_queue is not None
        assert settings.azure_service_bus_queue is not None
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        repository = SqlAlchemySubmissionOutboxRepository(sessions)
        generation_queue = AzureServiceBusGenerationQueue(
            namespace=settings.azure_service_bus_namespace,
            queue_name=settings.azure_service_bus_generation_queue,
        )
        conversion_queue = AzureServiceBusConversionQueue(
            namespace=settings.azure_service_bus_namespace,
            queue_name=settings.azure_service_bus_queue,
        )
        dispatcher = SubmissionOutboxDispatcher(
            repository,
            AzureServiceBusSubmissionTransport(generation_queue, conversion_queue),
            OutboxDispatcherConfig(
                claim_lease_seconds=settings.outbox_dispatcher_claim_lease_seconds,
                known_failure_retry_delay=timedelta(
                    seconds=settings.outbox_dispatcher_known_failure_retry_seconds
                ),
            ),
        )
        return cls(dispatcher, repository, engine, generation_queue, conversion_queue)

    async def run_once(self, *, max_messages: int, max_runtime_seconds: int) -> DispatcherExitCode:
        dispatcher_id = uuid4()
        try:
            await self.access_validator.validate_access()
            result = await asyncio.wait_for(
                self.dispatcher.run_once(dispatcher_id=dispatcher_id, max_messages=max_messages),
                timeout=max_runtime_seconds,
            )
        except TimeoutError:
            logger.error("Dispatcher execution reached its configured time limit.")
            return DispatcherExitCode.UNCERTAIN
        except asyncio.CancelledError:
            logger.warning("Dispatcher execution was cancelled; started sends remain uncertain.")
            raise
        except Exception as error:
            logger.error("Dispatcher execution failed before completion: %s", type(error).__name__)
            return DispatcherExitCode.FAILED
        if result.release_blocked:
            return DispatcherExitCode.RELEASE_BLOCKED
        if result.uncertain_count:
            return DispatcherExitCode.UNCERTAIN
        return DispatcherExitCode.SUCCESS

    async def close(self) -> None:
        errors: list[Exception] = []
        for resource in (self.generation_queue, self.conversion_queue):
            try:
                await resource.close()
            except Exception as error:
                errors.append(error)
        if self.engine is not None:
            try:
                await self.engine.dispose()
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError(
                "Dispatcher runtime could not cleanly close its resources."
            ) from errors[0]


def _validate_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("DATABASE_URL", settings.database_url),
            ("AZURE_SERVICE_BUS_NAMESPACE", settings.azure_service_bus_namespace),
            ("AZURE_SERVICE_BUS_GENERATION_QUEUE", settings.azure_service_bus_generation_queue),
            ("AZURE_SERVICE_BUS_QUEUE", settings.azure_service_bus_queue),
        )
        if not value
    ]
    if missing:
        raise ValueError("Dispatcher configuration is incomplete: " + ", ".join(missing))


async def run(
    settings: Settings, *, max_messages: int, max_runtime_seconds: int
) -> DispatcherExitCode:
    runtime = DispatcherRuntime.from_settings(settings)
    try:
        return await runtime.run_once(
            max_messages=max_messages, max_runtime_seconds=max_runtime_seconds
        )
    finally:
        await runtime.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch pending submission-outbox records once.")
    parser.add_argument("--max-messages", type=int)
    parser.add_argument("--max-runtime-seconds", type=int)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    arguments = _arguments()
    settings = get_settings()
    max_messages = arguments.max_messages or settings.outbox_dispatcher_max_messages
    max_runtime_seconds = (
        arguments.max_runtime_seconds or settings.outbox_dispatcher_max_runtime_seconds
    )
    if max_messages <= 0 or max_runtime_seconds <= 0:
        logger.error("Dispatcher limits must be positive.")
        return int(DispatcherExitCode.FAILED)
    try:
        return int(
            asyncio.run(
                run(settings, max_messages=max_messages, max_runtime_seconds=max_runtime_seconds)
            )
        )
    except ValueError as error:
        logger.error("Dispatcher configuration is invalid: %s", error)
    except Exception as error:
        logger.error(
            "Dispatcher runtime could not start or shut down safely: %s", type(error).__name__
        )
    return int(DispatcherExitCode.FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
