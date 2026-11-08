from contextvars import ContextVar, Token
import os
import uuid


def is_shared_workspace() -> bool:
    """Team mode: every signed-in user sees and edits the same presentations,
    templates and assets (needed for real-time co-editing). Off by default."""
    return os.getenv("PRESENTON_SHARED_WORKSPACE", "").strip().lower() in {"1", "true", "yes"}


_CURRENT_OWNER_ID: ContextVar[uuid.UUID | None] = ContextVar(
    "presenton_current_owner_id", default=None
)
_CURRENT_OWNER_IS_ADMIN: ContextVar[bool] = ContextVar(
    "presenton_current_owner_is_admin", default=False
)


def get_current_owner_id() -> uuid.UUID | None:
    # Owner scoping (row filters, owner stamping, per-user asset folders) keys off
    # this value; returning None in team mode makes all data workspace-wide.
    if is_shared_workspace():
        return None
    return _CURRENT_OWNER_ID.get()


def get_current_actor_id() -> uuid.UUID | None:
    """Credential identity must stay user-specific even in a shared workspace."""
    return _CURRENT_OWNER_ID.get()


def get_current_owner_is_admin() -> bool:
    return _CURRENT_OWNER_IS_ADMIN.get()


def set_current_owner_id(owner_id: uuid.UUID | None) -> Token:
    return _CURRENT_OWNER_ID.set(owner_id)


def set_current_owner_is_admin(is_admin: bool) -> Token:
    return _CURRENT_OWNER_IS_ADMIN.set(is_admin)


def reset_current_owner_id(token: Token) -> None:
    _CURRENT_OWNER_ID.reset(token)


def reset_current_owner_is_admin(token: Token) -> None:
    _CURRENT_OWNER_IS_ADMIN.reset(token)
