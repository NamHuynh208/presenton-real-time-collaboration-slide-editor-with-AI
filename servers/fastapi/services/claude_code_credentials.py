import base64
import hashlib
from datetime import timedelta
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.config import get_or_create_auth_secret
from models.sql.claude_code_credential import ClaudeCodeCredential
from utils.datetime_utils import get_current_utc_datetime


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
