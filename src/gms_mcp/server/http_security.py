"""Local Streamable HTTP authentication primitives."""

from __future__ import annotations

import hashlib
import hmac
import re

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

_MINIMUM_TOKEN_LENGTH = 32
_MAXIMUM_TOKEN_LENGTH = 4096
_BEARER_TOKEN = re.compile(r"^[A-Za-z0-9._~+/\-]+={0,2}$")


def validate_local_bearer_token(token: str) -> None:
    """Reject bearer tokens that are weak or invalid for an HTTP header."""
    if not _MINIMUM_TOKEN_LENGTH <= len(token) <= _MAXIMUM_TOKEN_LENGTH:
        raise ValueError("The local HTTP bearer token has an invalid length.")
    if _BEARER_TOKEN.fullmatch(token) is None:
        raise ValueError("The local HTTP bearer token contains invalid bearer-token characters.")


class LocalBearerTokenVerifier:
    """Verify one locally configured bearer token without retaining its plaintext."""

    def __init__(self, token: str) -> None:
        validate_local_bearer_token(token)
        self._token_digest = hashlib.sha256(token.encode("utf-8")).digest()

    async def verify_token(self, token: str) -> AccessToken | None:
        candidate_digest = hashlib.sha256(token.encode("utf-8")).digest()
        if not hmac.compare_digest(candidate_digest, self._token_digest):
            return None
        return AccessToken(token="", client_id="gms-mcp-local-http", scopes=[])


def local_bearer_auth(token: str, issuer_url: str) -> tuple[AuthSettings, LocalBearerTokenVerifier]:
    """Create SDK-native Bearer authentication for a loopback HTTP endpoint."""
    resource_url = AnyHttpUrl(issuer_url)
    return (
        AuthSettings(issuer_url=resource_url, resource_server_url=resource_url),
        LocalBearerTokenVerifier(token),
    )
