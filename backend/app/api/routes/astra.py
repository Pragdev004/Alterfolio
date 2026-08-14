from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies.astra import build_astra_tool_executor, get_astra_query_service
from app.api.dependencies.auth import get_astra_authenticated_principal
from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.schemas.astra import AstraErrorResponse, AstraQueryRequest, AstraQueryResponse
from app.services.ai.astra_query_service import AstraQueryService, AstraServiceError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/query",
    response_model=AstraQueryResponse,
    responses={
        401: {"model": AstraErrorResponse},
        422: {"model": AstraErrorResponse},
        403: {"model": AstraErrorResponse},
        502: {"model": AstraErrorResponse},
        504: {"model": AstraErrorResponse},
        500: {"model": AstraErrorResponse},
    },
)
async def astra_query(
    request: Request,
    service: AstraQueryService = Depends(get_astra_query_service),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        principal = get_astra_authenticated_principal(request)
    except HTTPException as exc:
        return _to_auth_error_response(exc)

    try:
        raw_payload = await request.json()
    except json.JSONDecodeError:
        return _invalid_request_response()

    if not isinstance(raw_payload, dict):
        return _invalid_request_response()

    try:
        parsed_payload = AstraQueryRequest.model_validate(raw_payload)
    except ValidationError:
        return _invalid_request_response()

    try:
        tool_executor = build_astra_tool_executor(
            db=db,
            principal=principal,
            settings=settings,
        )
        result = service.execute(
            query=parsed_payload.query,
            principal=principal,
            tool_executor=tool_executor,
        )
    except AstraServiceError as exc:
        logger.info(
            "astra.query.error",
            extra={
                "agent_run_id": str(exc.agent_run_id),
                "route": "/astra/query",
                "status": "failure",
                "error_code": exc.code,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "agent_run_id": str(exc.agent_run_id),
            },
        )

    return {
        "answer": result.answer,
        "agent_run_id": result.agent_run_id,
    }


def _invalid_request_response() -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "invalid_request",
            "message": "Invalid request payload",
            "agent_run_id": None,
        },
    )


def _to_auth_error_response(exc: HTTPException) -> JSONResponse:
    code = "authentication_required"
    message = "Authentication required"
    if str(exc.detail).lower().startswith("invalid"):
        code = "invalid_authenticated_principal"
        message = "Invalid authenticated principal"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "message": message,
            "agent_run_id": None,
        },
    )
