from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

RFC_4122_VARIANT = UUID("00000000-0000-4000-8000-000000000000").variant


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID):
            raise TypeError("AuthenticatedPrincipal.user_id must be a UUID")
        if self.user_id.int == 0:
            raise ValueError("AuthenticatedPrincipal.user_id must be non-empty")
        if self.user_id.variant != RFC_4122_VARIANT:
            raise ValueError("AuthenticatedPrincipal.user_id must use RFC 4122 variant")
        if self.user_id.version is None:
            raise ValueError("AuthenticatedPrincipal.user_id must include a UUID version")
        if self.user_id.version not in {1, 3, 4, 5, 6, 7, 8}:
            raise ValueError("AuthenticatedPrincipal.user_id has unsupported UUID version")
