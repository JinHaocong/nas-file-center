"""Administrator-only browser entry for the official ZSpace authorization process."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.auth.dependencies import get_current_session, require_admin_user
from app.batch.zspace_authorization import ZSpaceAuthorizationError
from app.models import Session


class _PrivateAuthorizationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            # The app-wide validator normally includes the rejected input.
            try:
                response = await handler(request)
            except RequestValidationError:
                raise HTTPException(422, "授权参数格式不正确", headers={"Cache-Control": "no-store"}) from None
            except ZSpaceAuthorizationError as exc:
                raise HTTPException(exc.status, str(exc), headers={"Cache-Control": "no-store"}) from None
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle


router = APIRouter(prefix="/api/settings/zspace-authorization", tags=["settings"],
                   dependencies=[Depends(require_admin_user)], route_class=_PrivateAuthorizationRoute)


class AuthorizationCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    code: SecretStr

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: SecretStr) -> SecretStr:
        code = value.get_secret_value().strip()
        if not re.fullmatch(r"[A-Za-z0-9]{4}(?:-[A-Za-z0-9]{4}){3}", code):
            raise ValueError("Invalid one-time authorization code")
        return SecretStr(code)


@router.get("")
def read_authorization(request: Request):
    return {"status": request.app.state.zspace_authorization.status()}


@router.post("/start")
def start_authorization(request: Request, session: Session = Depends(get_current_session)):
    return request.app.state.zspace_authorization.start(session.token_hash)


@router.post("/complete")
def complete_authorization(request: Request, payload: AuthorizationCompletion,
                           session: Session = Depends(get_current_session)):
    return request.app.state.zspace_authorization.complete(
        session.token_hash, payload.id, payload.code.get_secret_value(),
    )


@router.delete("/pending/{authorization_id}", status_code=204, response_class=Response)
def cancel_authorization(request: Request, authorization_id: str,
                         session: Session = Depends(get_current_session)):
    request.app.state.zspace_authorization.cancel(session.token_hash, authorization_id)
    return Response(status_code=204)
