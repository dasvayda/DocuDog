#!/usr/bin/env python3
"""Offline contract tests for the opt-in remote MCP safety boundary."""

from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog.remote_mcp import (  # noqa: E402
    BearerTokenGate,
    RemoteMcpConfigurationError,
    resolve_settings,
)


def _cfg(**overrides: object) -> dict:
    raw = {"enabled": True, "host": "127.0.0.1", "port": 8765, "path": "/mcp"}
    raw.update(overrides)
    return {"remote_mcp_settings": raw}


def _raises(cfg: dict, env: dict[str, str], expected: str) -> None:
    try:
        resolve_settings(cfg, env)
    except RemoteMcpConfigurationError as exc:
        assert expected in str(exc), str(exc)
    else:
        raise AssertionError("expected configuration error")


def main() -> int:
    _raises({"remote_mcp_settings": {"enabled": False}}, {}, "enabled")
    _raises(_cfg(), {}, "DOCUDOG_REMOTE_MCP_TOKEN")
    _raises(_cfg(), {"DOCUDOG_REMOTE_MCP_TOKEN": "short"}, "24 characters")
    _raises(
        _cfg(host="0.0.0.0"),
        {"DOCUDOG_REMOTE_MCP_TOKEN": "x" * 32},
        "allow_nonlocal_bind",
    )
    _raises(
        _cfg(host="0.0.0.0", allow_nonlocal_bind=True),
        {"DOCUDOG_REMOTE_MCP_TOKEN": "x" * 32},
        "allowed_hosts",
    )
    settings = resolve_settings(
        _cfg(), {"DOCUDOG_REMOTE_MCP_TOKEN": "x" * 32}
    )
    assert settings.endpoint == "http://127.0.0.1:8765/mcp"

    events: list[dict] = []

    async def app(scope, receive, send):
        events.append({"type": "ok"})

    async def call(auth: str):
        async def send(message):
            events.append(message)

        await BearerTokenGate(app, "x" * 32)(
            {"type": "http", "headers": [(b"authorization", auth.encode())]},
            None,
            send,
        )

    asyncio.run(call("Bearer wrong"))
    assert any(event.get("status") == 401 for event in events)
    events.clear()
    asyncio.run(call("Bearer " + "x" * 32))
    assert events == [{"type": "ok"}]
    print("remote MCP safety tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
