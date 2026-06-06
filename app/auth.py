"""Channel-scoped bearer auth for the mock Booking API (doc 12).

Tokens are scoped per channel. For the prototype these are static demo tokens; a real
deployment would issue/rotate scoped credentials.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from meridian.domain.enums import Channel

CHANNEL_TOKENS: dict[str, Channel] = {f"mock-{channel.value}-token": channel for channel in Channel}
"""Static demo tokens, one per channel (e.g. ``mock-agent-token`` → ``agent``)."""


def channel_for_token(token: str) -> Channel | None:
    """Return the channel a token is scoped to, or ``None`` if unknown."""
    return CHANNEL_TOKENS.get(token)


def require_channel(authorization: str | None = Header(default=None)) -> Channel:
    """FastAPI dependency: validate the bearer token and return its channel scope.

    Raises:
        HTTPException: 401 if the token is missing/malformed/unknown.
    """
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or malformed bearer token.")
    channel = channel_for_token(authorization.split(" ", 1)[1].strip())
    if channel is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token.")
    return channel
