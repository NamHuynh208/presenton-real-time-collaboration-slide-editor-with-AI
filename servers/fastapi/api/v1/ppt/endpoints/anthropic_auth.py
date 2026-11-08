import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.get_env import get_anthropic_api_key_env
from utils.set_env import set_anthropic_api_key_env
from utils.user_config import save_anthropic_api_key_to_user_config
from utils.oauth.anthropic_claude import (
    ClaudeTokens,
    create_api_key,
    create_authorization_flow,
    exchange_code,
    refresh_token,
)

ANTHROPIC_AUTH_ROUTER = APIRouter(prefix="/anthropic/auth", tags=["Anthropic OAuth"])
_sessions: dict[str, dict[str, str]] = {}


class ExchangeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=2000)


def _store(tokens: ClaudeTokens) -> dict:
    try:
        api_key = create_api_key(tokens.access_token)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Claude Code login succeeded, but creating an Anthropic API credential failed") from exc
    set_anthropic_api_key_env(api_key)
    save_anthropic_api_key_to_user_config()
    return {
        "status": "authenticated",
        "api_key": api_key,
        "expires_at": int(time.time() * 1000) + tokens.expires_at * 1000,
    }


@ANTHROPIC_AUTH_ROUTER.post("/initiate")
async def initiate_anthropic_auth():
    flow = create_authorization_flow()
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {"verifier": flow.verifier}
    return {"session_id": session_id, "url": flow.url}


@ANTHROPIC_AUTH_ROUTER.post("/exchange")
async def exchange_anthropic_auth(body: ExchangeRequest):
    session = _sessions.pop(body.session_id, None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or already consumed")
    try:
        return _store(exchange_code(body.code, session["verifier"]))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not exchange the Claude Code authorization code") from exc


@ANTHROPIC_AUTH_ROUTER.get("/status")
async def anthropic_auth_status():
    return {"status": "authenticated" if get_anthropic_api_key_env() else "unauthenticated"}


@ANTHROPIC_AUTH_ROUTER.post("/refresh")
async def refresh_anthropic_auth():
    raise HTTPException(status_code=400, detail="Please sign in to Claude Code again")


@ANTHROPIC_AUTH_ROUTER.post("/logout")
async def logout_anthropic_auth():
    set_anthropic_api_key_env("")
    save_anthropic_api_key_to_user_config()
    return {"status": "unauthenticated"}
