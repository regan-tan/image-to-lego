import asyncio
from dataclasses import dataclass

import pytest

from app.core.config import Settings
from app.outbox.dispatcher import DispatchRunResult
from app.outbox.run import DispatcherExitCode, DispatcherRuntime, _validate_settings


@dataclass
class FakeDispatcher:
    result: DispatchRunResult | None = None
    error: Exception | None = None
    block: asyncio.Event | None = None
    validated: bool = False

    async def validate_access(self) -> None:
        self.validated = True
        if self.error is not None:
            raise self.error

    async def run_once(self, *, dispatcher_id: object, max_messages: int) -> DispatchRunResult:
        del dispatcher_id, max_messages
        if self.block is not None:
            await self.block.wait()
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FakeClosable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _runtime(dispatcher: FakeDispatcher) -> tuple[DispatcherRuntime, FakeClosable, FakeClosable]:
    generation = FakeClosable()
    conversion = FakeClosable()
    return (
        DispatcherRuntime(dispatcher, dispatcher, None, generation, conversion),
        generation,
        conversion,
    )


def test_runtime_construction_requires_complete_configuration() -> None:
    with pytest.raises(ValueError, match="AZURE_SERVICE_BUS_NAMESPACE"):
        _validate_settings(
            Settings(
                database_url="postgresql+asyncpg://localhost/app",
                azure_service_bus_namespace="",
                azure_service_bus_generation_queue="generation",
                azure_service_bus_queue="conversion",
            )
        )


async def test_successful_bounded_execution_and_clean_shutdown() -> None:
    runtime, generation, conversion = _runtime(
        FakeDispatcher(result=DispatchRunResult(1, 0, 0, False))
    )

    assert (
        await runtime.run_once(max_messages=1, max_runtime_seconds=1) is DispatcherExitCode.SUCCESS
    )
    await runtime.close()

    assert generation.closed is True
    assert conversion.closed is True


async def test_uncertain_or_timed_out_execution_cannot_succeed() -> None:
    runtime, _, _ = _runtime(FakeDispatcher(result=DispatchRunResult(0, 0, 1, False)))
    assert (
        await runtime.run_once(max_messages=1, max_runtime_seconds=1)
        is DispatcherExitCode.UNCERTAIN
    )

    timed_out, _, _ = _runtime(FakeDispatcher(block=asyncio.Event()))
    assert (
        await timed_out.run_once(max_messages=1, max_runtime_seconds=0.01)
        is DispatcherExitCode.UNCERTAIN
    )
