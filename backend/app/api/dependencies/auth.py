from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request

from app.core.config import Settings, get_settings


def _get_principal_from_request_state(request: Request) -> UUID | None:
    candidate = getattr(request.state, "authenticated_user_id", None)

    if candidate is None:
        candidate = getattr(request.state, "user_id", None)

    if candidate is None:
        return None

    if isinstance(candidate, UUID):
        return candidate

    try:
        return UUID(str(candidate))
    except (TypeError, ValueError):
        return None


def get_authenticated_user_id(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    settings: Settings = Depends(get_settings),
) -> UUID:
    principal_from_state = _get_principal_from_request_state(request)
    if principal_from_state is not None:
        return principal_from_state

    if x_user_id:
        try:
            return UUID(x_user_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=401,
                detail="Invalid authenticated principal",
            ) from exc

    if settings.environment.lower() != "production":
        return settings.default_dev_user_id

    raise HTTPException(
        status_code=401,
        detail="Authentication required",
    )
