import base64
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.config import get_or_create_auth_secret
from models.sql.claude_code_credential import ClaudeCodeCredential
from utils.datetime_utils import get_current_utc_datetime
from utils.db_utils import get_database_url_and_connect_args, to_sync_sqlalchemy_url
from utils.oauth.anthropic_claude import refresh_token
import threading

_refresh_lock = threading.Lock()


def _cipher() -> Fernet:
    key = hashlib.sha256(
        b"presenton-claude-code-credentials-v1:" + get_or_create_auth_secret().encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(value: str | None) -> str | None:
    return _cipher().encrypt(value.encode()).decode() if value else None


async def get_credential(session: AsyncSession, user_id: UUID) -> ClaudeCodeCredential | None:
    return await session.scalar(
        select(ClaudeCodeCredential).where(ClaudeCodeCredential.user_id == user_id)
    )


async def store_credential(
    session: AsyncSession,
    *,
    user_id: UUID,
    email: str | None,
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
) -> ClaudeCodeCredential:
    credential = await get_credential(session, user_id)
    if credential is None:
        credential = ClaudeCodeCredential(
            user_id=user_id,
            access_token_encrypted="placeholder",
            token_expires_at=get_current_utc_datetime(),
        )
    credential.email = email
    credential.access_token_encrypted = _encrypt(access_token) or "placeholder"
    credential.refresh_token_encrypted = _encrypt(refresh_token)
    credential.token_expires_at = get_current_utc_datetime() + timedelta(seconds=max(1, expires_in))
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return credential


async def delete_credential(session: AsyncSession, user_id: UUID) -> None:
    credential = await get_credential(session, user_id)
    if credential is not None:
        await session.delete(credential)
        await session.commit()


def get_access_token(user_id: UUID) -> str:
    """Used by synchronous LLM clients, including generation worker threads."""
    url, _ = get_database_url_and_connect_args()
    engine = create_engine(to_sync_sqlalchemy_url(url))
    try:
        # shortcut: one API process; use a distributed refresh lock before scaling workers.
        with _refresh_lock, Session(engine) as session:
            credential = session.scalar(select(ClaudeCodeCredential).where(
                ClaudeCodeCredential.user_id == user_id
            ).with_for_update())
            if credential is None:
                raise HTTPException(401, "Connect your Claude Code account first.")
            expires = credential.token_expires_at.replace(tzinfo=UTC)
            if expires <= datetime.now(UTC) + timedelta(seconds=60):
                if not credential.refresh_token_encrypted:
                    raise HTTPException(401, "Claude Code session expired. Sign in again.")
                refresh = _cipher().decrypt(credential.refresh_token_encrypted.encode()).decode()
                try:
                    tokens = refresh_token(refresh)
                except Exception:
                    raise HTTPException(401, "Could not renew your Claude Code session. Sign in again.") from None
                credential.access_token_encrypted = _encrypt(tokens.access_token)
                credential.refresh_token_encrypted = _encrypt(tokens.refresh_token)
                credential.token_expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_at)
                session.commit()
            return _cipher().decrypt(credential.access_token_encrypted.encode()).decode()
    except InvalidToken:
        raise HTTPException(401, "Stored Claude Code credentials cannot be decrypted. Sign in again.") from None
    finally:
        engine.dispose()
