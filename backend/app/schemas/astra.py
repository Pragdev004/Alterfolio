from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AstraQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("query must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be empty")

        if "\x00" in normalized:
            raise ValueError("query contains invalid characters")

        return normalized


class AstraQueryResponse(BaseModel):
    answer: str
    agent_run_id: UUID


class AstraErrorResponse(BaseModel):
    code: str
    message: str
    agent_run_id: UUID | None = None
