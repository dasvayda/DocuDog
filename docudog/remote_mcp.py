"""Safety boundary for the opt-in Streamable HTTP MCP gateway."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


class RemoteMcpConfigurationError(ValueError):
    """Raised when an opt-in remote MCP configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class RemoteMcpSettings:
    host: str
    port: int
    path: str
    token_env_var: str
    token: str
    allowed_hosts: list[str]
    allowed_origins: list[str]

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}{self.path}"


def _string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RemoteMcpConfigurationError(
            f"remote_mcp_settings.{name} must be a list of strings"
        )
    return [item.strip() for item in value if item.strip()]


def resolve_settings(
    cfg: dict[str, Any], environ: dict[str, str] | None = None
) -> RemoteMcpSettings:
    """Validate explicit gateway settings and retrieve its secret from the environment."""
    raw = cfg.get("remote_mcp_settings")
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        raise RemoteMcpConfigurationError(
            "remote_mcp_settings.enabled must be true before starting the HTTP gateway"
        )
    host = str(raw.get("host") or "127.0.0.1").strip()
    loopback = {"127.0.0.1", "::1", "localhost"}
    if host not in loopback:
        if raw.get("allow_nonlocal_bind") is not True:
            raise RemoteMcpConfigurationError(
                "non-loopback binding requires remote_mcp_settings.allow_nonlocal_bind=true"
            )
        if not _string_list(raw.get("allowed_hosts"), "allowed_hosts"):
            raise RemoteMcpConfigurationError(
                "non-loopback binding requires remote_mcp_settings.allowed_hosts"
            )
    try:
        port = int(raw.get("port", 8765))
    except (TypeError, ValueError) as exc:
        raise RemoteMcpConfigurationError(
            "remote_mcp_settings.port must be an integer"
        ) from exc
    if not 1 <= port <= 65535:
        raise RemoteMcpConfigurationError(
            "remote_mcp_settings.port must be between 1 and 65535"
        )
    path = str(raw.get("path") or "/mcp").strip()
    if not path.startswith("/") or "?" in path or "#" in path:
        raise RemoteMcpConfigurationError(
            "remote_mcp_settings.path must be an absolute URL path"
        )
    token_env_var = str(
        raw.get("token_env_var") or "DOCUDOG_REMOTE_MCP_TOKEN"
    ).strip()
    if not token_env_var or not token_env_var.replace("_", "").isalnum():
        raise RemoteMcpConfigurationError(
            "remote_mcp_settings.token_env_var must be an environment-variable name"
        )
    source = os.environ if environ is None else environ
    token = str(source.get(token_env_var) or "")
    if len(token) < 24:
        raise RemoteMcpConfigurationError(
            f"set {token_env_var} to a random token of at least 24 characters before starting"
        )
    return RemoteMcpSettings(
        host=host,
        port=port,
        path=path,
        token_env_var=token_env_var,
        token=token,
        allowed_hosts=_string_list(raw.get("allowed_hosts"), "allowed_hosts"),
        allowed_origins=_string_list(raw.get("allowed_origins"), "allowed_origins"),
    )


class BearerTokenGate:
    """ASGI guard for one explicitly configured access token."""

    def __init__(self, app: Callable[..., Awaitable[None]], token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            bytes(key).lower(): bytes(value)
            for key, value in scope.get("headers", [])
        }
        received = headers.get(b"authorization", b"").decode("latin-1")
        if not hmac.compare_digest(received, f"Bearer {self.token}"):
            body = b'{"error":"authentication_required"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
