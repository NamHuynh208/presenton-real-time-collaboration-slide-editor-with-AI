import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.users import get_current_user
from models.sql.user import User
from services.claude_code_credentials import delete_credential, get_credential, store_credential
from services.database import get_async_session
from utils.oauth.anthropic_claude import (
    create_authorization_flow,
    exchange_code,
)

ANTHROPIC_AUTH_ROUTER = APIRouter(prefix="/anthropic/auth", tags=["Anthropic OAuth"])
_sessions: dict[str, dict[str, str]] = {}


class ExchangeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=2000)


@ANTHROPIC_AUTH_ROUTER.post("/initiate")
async def initiate_anthropic_auth(
    current_user: User = Depends(get_current_user),
):
    flow = create_authorization_flow()
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {"verifier": flow.verifier, "user_id": str(current_user.id)}
    return {"session_id": session_id, "url": flow.url}


@ANTHROPIC_AUTH_ROUTER.post("/exchange")
async def exchange_anthropic_auth(
    body: ExchangeRequest,
    db_session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    link_session = _sessions.pop(body.session_id, None)
    if not link_session:
        raise HTTPException(status_code=404, detail="Session not found or already consumed")
    try:
        tokens = exchange_code(body.code, link_session["verifier"])
        if link_session["user_id"] != str(current_user.id):
            raise HTTPException(status_code=403, detail="This Claude Code link belongs to another user")
        await store_credential(
            db_session,
            user_id=current_user.id,
            email=current_user.username,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_at,
        )
        return {"status": "authenticated", "detail": "Claude Code linked"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not exchange the Claude Code authorization code") from exc


@ANTHROPIC_AUTH_ROUTER.get("/status")
async def anthropic_auth_status(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    return {"status": "authenticated" if await get_credential(session, current_user.id) else "unauthenticated"}


@ANTHROPIC_AUTH_ROUTER.post("/refresh")
async def refresh_anthropic_auth():
    raise HTTPException(status_code=400, detail="Please sign in to Claude Code again")


@ANTHROPIC_AUTH_ROUTER.post("/logout")
async def logout_anthropic_auth(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    await delete_credential(session, current_user.id)
    return {"status": "unauthenticated"}
