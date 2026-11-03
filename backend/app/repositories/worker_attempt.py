from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class AttemptAcquisitionStatus(StrEnum):
    ACQUIRED = "acquired"
    TERMINAL_OR_DUPLICATE = "terminal_or_duplicate"
    LEASE_HELD = "lease_held"
    RELEASE_BLOCKED = "release_blocked"


@dataclass(frozen=True, slots=True)
class AttemptAcquisition:
    """The durable reason a queue delivery did or did not obtain a job lease."""

    status: AttemptAcquisitionStatus
    attempt_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.status is AttemptAcquisitionStatus.ACQUIRED) != (self.attempt_id is not None):
            raise ValueError("Only an acquired attempt may include an attempt ID.")
