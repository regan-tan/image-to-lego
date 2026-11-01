"""Fail-closed orchestration for a fenced worker release."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol
from uuid import UUID


class ReleaseOwnershipLost(RuntimeError):
    """The controller no longer owns the durable release gate."""


class ReleaseBlocked(RuntimeError):
    """Required release evidence could not be established."""


class ReleaseCoordination(Protocol):
    async def begin(self, release_id: UUID, controller_id: UUID, heartbeat_seconds: int) -> int: ...

    async def heartbeat(
        self, release_id: UUID, controller_id: UUID, fencing_token: int, heartbeat_seconds: int
    ) -> None: ...

    async def transition(
        self, release_id: UUID, controller_id: UUID, fencing_token: int, state: str, detail: str
    ) -> None: ...


class ReleaseEvidence(Protocol):
    async def is_quiescent(self) -> tuple[bool, str]: ...


class ReleaseDeployment(Protocol):
    async def deploy(self) -> str: ...

    async def verify(self) -> tuple[bool, str]: ...


@dataclass(frozen=True, slots=True)
class ReleaseControllerConfig:
    heartbeat_seconds: int
    heartbeat_interval: timedelta
    quiescence_poll_interval: timedelta
    quiescence_timeout: timedelta


@dataclass(slots=True)
class ReleaseReport:
    release_id: UUID
    controller_id: UUID
    fencing_token: int | None = None
    events: list[str] = field(default_factory=list)
    final_state: str = "blocked"


class ReleaseController:
    """Coordinates durable state; deployment and observations remain injectable side effects."""

    def __init__(
        self,
        coordination: ReleaseCoordination,
        evidence: ReleaseEvidence,
        deployment: ReleaseDeployment,
        config: ReleaseControllerConfig,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._coordination = coordination
        self._evidence = evidence
        self._deployment = deployment
        self._config = config
        self._sleep = sleep

    async def run(self, release_id: UUID, controller_id: UUID) -> ReleaseReport:
        report = ReleaseReport(release_id=release_id, controller_id=controller_id)
        token = await self._coordination.begin(
            release_id, controller_id, self._config.heartbeat_seconds
        )
        report.fencing_token = token
        report.events.append("gate draining")
        heartbeat_failed = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._maintain_heartbeat(release_id, controller_id, token, heartbeat_failed)
        )
        try:
            await self._wait_for_quiescence(heartbeat_failed, report)
            await self._transition(release_id, controller_id, token, "quiescent", report)
            await self._transition(release_id, controller_id, token, "deploying", report)
            report.events.append(await self._deployment.deploy())
            await self._assert_owner(heartbeat_failed)
            await self._transition(release_id, controller_id, token, "verifying", report)
            verified, detail = await self._deployment.verify()
            if not verified:
                raise ReleaseBlocked(detail)
            report.events.append(detail)
            await self._transition(release_id, controller_id, token, "open", report)
            report.final_state = "open"
            return report
        except BaseException as error:
            await self._block_if_owned(release_id, controller_id, token, report, str(error))
            raise
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _wait_for_quiescence(self, failed: asyncio.Event, report: ReleaseReport) -> None:
        remaining = self._config.quiescence_timeout.total_seconds()
        interval = self._config.quiescence_poll_interval.total_seconds()
        while remaining >= 0:
            await self._assert_owner(failed)
            quiescent, detail = await self._evidence.is_quiescent()
            if quiescent:
                report.events.append(detail)
                return
            await self._sleep(interval)
            remaining -= interval
        raise ReleaseBlocked("Timed out waiting for independently verified quiescence.")

    async def _maintain_heartbeat(
        self, release_id: UUID, controller_id: UUID, token: int, failed: asyncio.Event
    ) -> None:
        try:
            while True:
                await self._sleep(self._config.heartbeat_interval.total_seconds())
                await self._coordination.heartbeat(
                    release_id, controller_id, token, self._config.heartbeat_seconds
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            failed.set()

    async def _assert_owner(self, failed: asyncio.Event) -> None:
        if failed.is_set():
            raise ReleaseOwnershipLost("Release controller heartbeat was rejected.")

    async def _transition(
        self, release_id: UUID, controller_id: UUID, token: int, state: str, report: ReleaseReport
    ) -> None:
        await self._coordination.transition(release_id, controller_id, token, state, state)
        report.events.append(state)

    async def _block_if_owned(
        self, release_id: UUID, controller_id: UUID, token: int, report: ReleaseReport, detail: str
    ) -> None:
        try:
            await self._coordination.transition(release_id, controller_id, token, "blocked", detail)
            report.events.append("blocked")
        except Exception:
            report.events.append("blocked state could not be recorded")
