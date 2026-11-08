import asyncio
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.auth.users import get_current_user
from api.v1.ppt.endpoints import anthropic_auth as auth
from models.sql.user import User
from services.database import get_async_session
from utils.oauth.anthropic_claude import ClaudeTokens


def test_link_session_cannot_be_consumed_by_another_web_user(monkeypatch):
    alice = User(id=uuid.uuid4(), username="alice", hashed_password="unused")
    bob = User(id=uuid.uuid4(), username="bob", hashed_password="unused")
    active = [alice]
    saved = []
    exchanged = []
    monkeypatch.setattr(auth, "_sessions", {})

    async def database():
        yield object()

    def exchange(code, verifier):
        exchanged.append(code)
        return ClaudeTokens("private-access", "private-refresh", 3600)

    async def store(db, **kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(auth, "exchange_code", exchange)
    monkeypatch.setattr(auth, "store_credential", store)
    app = FastAPI()
    app.include_router(auth.ANTHROPIC_AUTH_ROUTER)
    app.dependency_overrides[get_current_user] = lambda: active[0]
    app.dependency_overrides[get_async_session] = database
    with TestClient(app) as client:
        started = client.post("/anthropic/auth/initiate").json()
        body = {"session_id": started["session_id"], "code": "code"}
        active[0] = bob
        assert client.post("/anthropic/auth/exchange", json=body).status_code == 403
        assert not exchanged and not saved
        active[0] = alice
        linked = client.post("/anthropic/auth/exchange", json=body)
        assert linked.status_code == 200
        assert "private-access" not in linked.text and "private-refresh" not in linked.text
        assert saved[0]["user_id"] == alice.id
        assert client.post("/anthropic/auth/exchange", json=body).status_code == 404


def test_expired_link_never_calls_provider(monkeypatch):
    user = User(id=uuid.uuid4(), username="alice", hashed_password="unused")
    monkeypatch.setattr(auth, "_sessions", {"expired": {"user_id": str(user.id), "verifier": "test", "expires": time.monotonic() - 1}})
    with pytest.raises(Exception) as failure:
        asyncio.run(auth.exchange_anthropic_auth(
            auth.ExchangeRequest(session_id="expired", code="code"), object(), user
        ))
    assert failure.value.status_code == 410
