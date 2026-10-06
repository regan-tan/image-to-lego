from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.core.errors import ApplicationError
from app.domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    source_artifact_id: UUID
    target_parts: int
    up_axis: Literal["x", "y", "z"] = "y"
    settings: dict[str, JsonValue] = field(default_factory=dict)


class ConversionService:
    """Validates conversion intent before future durable job scheduling."""

    def prepare(self, request: ConversionRequest) -> ConversionRequest:
        if request.target_parts <= 0:
            raise ApplicationError(
                code="invalid_target_parts",
                message="Target parts must be greater than zero.",
            )
        return request
