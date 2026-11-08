import asyncio
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.users import get_current_user
from models.sql.user import User
from services.claude_code_credentials import delete_credential, get_access_token, get_credential, store_credential
from services.database import get_async_session
from utils.oauth.anthropic_claude import (
    create_authorization_flow,
    exchange_code,
)

ANTHROPIC_AUTH_ROUTER = APIRouter(prefix="/anthropic/auth", tags=["Anthropic OAuth"])
_sessions: dict[str, dict] = {}


class ExchangeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=2000)


@ANTHROPIC_AUTH_ROUTER.post("/initiate")
async def initiate_anthropic_auth(
    current_user: User = Depends(get_current_user),
):
    flow = create_authorization_flow()
    now = time.monotonic()
    for key, value in list(_sessions.items()):
        if value["expires"] <= now or value["user_id"] == str(current_user.id):
            _sessions.pop(key, None)
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {"verifier": flow.verifier, "user_id": str(current_user.id), "expires": now + 600}
    return {"session_id": session_id, "url": flow.url}


@ANTHROPIC_AUTH_ROUTER.post("/exchange")
async def exchange_anthropic_auth(
    body: ExchangeRequest,
    db_session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    link_session = _sessions.get(body.session_id)
    if not link_session:
        raise HTTPException(status_code=404, detail="Session not found or already consumed")
    if link_session["user_id"] != str(current_user.id):
        raise HTTPException(status_code=403, detail="This Claude Code link belongs to another user")
    if link_session["expires"] <= time.monotonic():
        _sessions.pop(body.session_id, None)
        raise HTTPException(410, "Claude Code link expired. Start sign-in again.")
    if link_session.get("exchanging"):
        raise HTTPException(409, "This Claude Code sign-in is already being completed.")
    link_session["exchanging"] = True
    try:
        tokens = await asyncio.to_thread(exchange_code, body.code, link_session["verifier"])
        await store_credential(
            db_session,
            user_id=current_user.id,
            email=None,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_at,
        )
        _sessions.pop(body.session_id, None)
        return {"status": "authenticated", "detail": "Claude Code linked"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not exchange the Claude Code authorization code") from exc
    finally:
        link_session["exchanging"] = False


@ANTHROPIC_AUTH_ROUTER.get("/status")
async def anthropic_auth_status(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    credential = await get_credential(session, current_user.id)
    linked = credential is not None
    usable = linked and (
        credential.token_expires_at.replace(tzinfo=UTC) > datetime.now(UTC)
        or bool(credential.refresh_token_encrypted)
    )
    return {"status": "authenticated" if usable else "unauthenticated"}


@ANTHROPIC_AUTH_ROUTER.post("/refresh")
async def refresh_anthropic_auth(current_user: User = Depends(get_current_user)):
    await asyncio.to_thread(get_access_token, current_user.id)
    return {"status": "authenticated"}


@ANTHROPIC_AUTH_ROUTER.post("/check")
async def check_claude_runtime(current_user: User = Depends(get_current_user)):
    from utils.claude_code_client import cli_executable

    cli_executable()
    await asyncio.to_thread(get_access_token, current_user.id)
    return {"status": "ready"}


@ANTHROPIC_AUTH_ROUTER.post("/logout")
async def logout_anthropic_auth(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    for key, value in list(_sessions.items()):
        if value["user_id"] == str(current_user.id):
            _sessions.pop(key, None)
    await delete_credential(session, current_user.id)
    return {"status": "unauthenticated"}
