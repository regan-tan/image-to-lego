from datetime import timedelta
from uuid import uuid4

import pytest

from app.release.controller import (
    ReleaseBlocked,
    ReleaseController,
    ReleaseControllerConfig,
    ReleaseOwnershipLost,
)


class FakeCoordination:
    def __init__(self, fail_heartbeat: bool = False) -> None:
        self.states: list[str] = []
        self.fail_heartbeat = fail_heartbeat

    async def begin(self, release_id: object, controller_id: object, heartbeat_seconds: int) -> int:
        return 1

    async def heartbeat(
        self, release_id: object, controller_id: object, token: int, seconds: int
    ) -> None:
        if self.fail_heartbeat:
            raise RuntimeError("fenced")

    async def transition(
        self, release_id: object, controller_id: object, token: int, state: str, detail: str
    ) -> None:
        self.states.append(state)


class FakeEvidence:
    def __init__(self, values: list[tuple[bool, str]]) -> None:
        self.values = values

    async def is_quiescent(self) -> tuple[bool, str]:
        return self.values.pop(0) if self.values else (False, "still active")


class FakeDeployment:
    def __init__(self, verified: bool = True) -> None:
        self.verified = verified

    async def deploy(self) -> str:
        return "fake deployment"

    async def verify(self) -> tuple[bool, str]:
        return self.verified, "fake readiness"


def _controller(
    coordination: FakeCoordination,
    evidence: FakeEvidence,
    deployment: FakeDeployment | None = None,
) -> ReleaseController:
    return ReleaseController(
        coordination,
        evidence,
        deployment or FakeDeployment(),
        ReleaseControllerConfig(
            1, timedelta(milliseconds=1), timedelta(milliseconds=1), timedelta(seconds=1)
        ),
    )


async def test_controller_runs_the_fenced_release_sequence() -> None:
    coordination = FakeCoordination()
    report = await _controller(coordination, FakeEvidence([(True, "all work drained")])).run(
        uuid4(), uuid4()
    )
    assert report.final_state == "open"
    assert coordination.states == ["quiescent", "deploying", "verifying", "open"]


async def test_controller_blocks_when_quiescence_cannot_be_proven() -> None:
    coordination = FakeCoordination()
    controller = _controller(coordination, FakeEvidence([(False, "unknown worker")]))
    with pytest.raises(ReleaseBlocked):
        await controller.run(uuid4(), uuid4())
    assert coordination.states[-1] == "blocked"


async def test_controller_stops_when_heartbeat_loses_ownership() -> None:
    coordination = FakeCoordination(fail_heartbeat=True)
    controller = _controller(coordination, FakeEvidence([(False, "waiting")]))
    with pytest.raises(ReleaseOwnershipLost):
        await controller.run(uuid4(), uuid4())
    assert "open" not in coordination.states


async def test_controller_does_not_reopen_after_failed_verification() -> None:
    coordination = FakeCoordination()
    controller = _controller(
        coordination,
        FakeEvidence([(True, "all work drained")]),
        FakeDeployment(verified=False),
    )

    with pytest.raises(ReleaseBlocked):
        await controller.run(uuid4(), uuid4())

    assert coordination.states == ["quiescent", "deploying", "verifying", "blocked"]
