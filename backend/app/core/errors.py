from dataclasses import dataclass


@dataclass(slots=True)
class ApplicationError(Exception):
    """Expected application failure that can be translated at an outer boundary."""

    code: str
    message: str
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
