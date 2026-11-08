"""Claude Code OAuth (PKCE) helpers.

The callback is deliberately the hosted Anthropic callback: it shows a code the
user can paste back into Presenton, so this works behind a reverse proxy.
"""
from dataclasses import dataclass
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from utils.oauth.pkce import generate_pkce

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPE = "org:create_api_key user:profile user:inference"


@dataclass
class ClaudeFlow:
    verifier: str
    state: str
    url: str


@dataclass
class ClaudeTokens:
    access_token: str
    refresh_token: str | None
    expires_at: int


def create_authorization_flow() -> ClaudeFlow:
    verifier, challenge = generate_pkce()
    # Claude Code uses the verifier as state; the exchange validates it too.
    state = verifier
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return ClaudeFlow(verifier, state, f"{AUTHORIZE_URL}?{urlencode(params)}")


def exchange_code(code: str, verifier: str) -> ClaudeTokens:
    value = code.strip()
    if value.startswith("https://"):
        parsed = urlparse(value)
        if parsed.hostname not in {"console.anthropic.com", "platform.claude.com"}:
            raise ValueError("Unexpected Claude callback host")
        params = parse_qs(parsed.query)
        value = params.get("code", [""])[0]
        incoming_state = params.get("state", [None])[0] or parsed.fragment or None
    else:
        value, _, incoming_state = value.partition("#")
    if not value or (incoming_state and not secrets.compare_digest(incoming_state, verifier)):
        raise ValueError("Invalid Claude authorization code or state")
    response = httpx.post(
        TOKEN_URL,
        json={
            "code": value,
            "state": verifier,
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise ValueError("Anthropic returned no access token")
    expires_in = int(payload.get("expires_in", 8 * 60 * 60))
    return ClaudeTokens(access, payload.get("refresh_token"), expires_in)


def refresh_token(refresh: str) -> ClaudeTokens:
    response = httpx.post(
        TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": CLIENT_ID,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise ValueError("Anthropic returned no refreshed access token")
    return ClaudeTokens(
        access,
        payload.get("refresh_token") or refresh,
        int(payload.get("expires_in", 8 * 60 * 60)),
    )
