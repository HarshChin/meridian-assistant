"""Channel-scoped bearer auth for the mock Booking API (doc 12).

Tokens are scoped per channel. For the prototype these are static demo tokens; a real
deployment would issue/rotate scoped credentials.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from meridian.domain.enums import Channel

CHANNEL_TOKENS: dict[str, Channel] = {f"mock-{channel.value}-token": channel for channel in Channel}
"""Static demo tokens, one per channel (e.g. ``mock-agent-token`` → ``agent``)."""

_bearer_scheme = HTTPBearer(auto_error=False, description="Bearer mock-<channel>-token")
"""Declared as an OpenAPI security scheme so Swagger renders an *Authorize* button and reliably
attaches the ``Authorization`` header to every request (a plain header parameter is dropped by
Swagger UI). ``auto_error=False`` lets us keep the spec's custom 401 messages below."""


def channel_for_token(token: str) -> Channel | None:
    """Return the channel a token is scoped to, or ``None`` if unknown."""
    return CHANNEL_TOKENS.get(token)


def require_channel(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Channel:
    """FastAPI dependency: validate the bearer token and return its channel scope.

    Raises:
        HTTPException: 401 if the token is missing/malformed/unknown.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or malformed bearer token.")
    channel = channel_for_token(credentials.credentials.strip())
    if channel is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token.")
    return channel
