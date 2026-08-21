#!/usr/bin/env python3
"""Smoke tests for the MCP search pagination and error contract."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog.mcp_service import McpService  # noqa: E402


def _service() -> McpService:
    svc = McpService(ROOT)
    svc.cfg = {"mcp_settings": {"enforce_allowlist": False}}
    files = {}
    for i in range(3):
        path = os.path.join(ROOT, "fixtures", f"contract_{i}.md")
        files[path] = {
            "file_id": f"contract-{i}",
            "security_level": "P4",
            "tags": ["contract"],
            "summary": f"contract item {i}",
            "last_analyzed_utc": f"2026-08-2{i + 1}T00:00:00+00:00",
        }
    svc.load_state = lambda **_kwargs: {"files": files}  # type: ignore[method-assign]
    return svc


def main() -> int:
    svc = _service()

    first = svc.search(query="contract", limit=2)
    assert first["ok"] is True
    assert first["offset"] == 0
    assert first["showing"] == 2
    assert first["has_more"] is True
    assert first["next_cursor"]

    second = svc.search(query="contract", limit=2, cursor=first["next_cursor"])
    assert second["ok"] is True
    assert second["offset"] == 2
    assert second["showing"] == 1
    assert second["has_more"] is False
    assert second["next_cursor"] is None

    offset_page = svc.search(query="contract", limit=1, offset=1)
    assert offset_page["ok"] is True
    assert offset_page["results"][0]["summary"] == "contract item 1"

    assert svc.search(limit=0)["code"] == "invalid_limit"
    assert svc.search(offset=-1)["code"] == "invalid_offset"
    assert svc.search(cursor="broken")["code"] == "invalid_cursor"
    assert svc.search(query="[", regex=True)["code"] == "invalid_regex"
    assert svc.search(offset=1, cursor=first["next_cursor"])["code"] == (
        "pagination_conflict"
    )

    missing = svc.get(path=os.path.join(ROOT, "missing-contract.md"))
    assert missing["ok"] is False
    assert missing["code"] == "not_found_in_state"
    print("all MCP contract tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
