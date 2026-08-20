#!/usr/bin/env python3
"""
DocuDog MCP server (stdio) + install helpers for Cursor / Claude Desktop.

Connect (for humans or coding agents):
  python tools/docudog_mcp.py --print-install
  python tools/docudog_mcp.py --write-cursor-mcp

Run as MCP (clients launch this):
  python tools/docudog_mcp.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _python_exe() -> str:
    return os.path.normpath(sys.executable)


def _server_script() -> str:
    return os.path.normpath(os.path.join(ROOT, "tools", "docudog_mcp.py"))


def build_mcp_server_entry(*, config_dir: str | None = None) -> dict:
    """JSON fragment under mcpServers.docudog (Cursor / Claude Desktop)."""
    cfg_dir = os.path.normpath(config_dir or ROOT)
    args = [_server_script()]
    # Always pin config dir so clients started from another cwd still work.
    args.extend(["--config-dir", cfg_dir])
    return {
        "command": _python_exe(),
        "args": args,
        "cwd": cfg_dir,
    }


def print_install(config_dir: str | None = None) -> None:
    entry = build_mcp_server_entry(config_dir=config_dir)
    cursor_path = os.path.join(ROOT, ".cursor", "mcp.json")
    claude_hint = os.path.expandvars(
        r"%APPDATA%\Claude\claude_desktop_config.json"
    )
    payload = {
        "docudog_root": ROOT,
        "python": _python_exe(),
        "server_script": _server_script(),
        "cursor": {
            "file": cursor_path,
            "mcpServers": {"docudog": entry},
        },
        "claude_desktop": {
            "file": claude_hint,
            "mcpServers": {"docudog": entry},
        },
        "agent_instructions": [
            "1. Ensure deps: pip install --user \"mcp[cli]\" (or -r requirements.txt).",
            "2. Prefer: python tools/docudog_mcp.py --write-cursor-mcp",
            "3. Or merge the cursor.mcpServers object into .cursor/mcp.json.",
            "4. For Claude Desktop, merge claude_desktop.mcpServers into "
            "claude_desktop_config.json and restart Claude.",
            "5. Verify with MCP tool docudog_ping.",
            "6. Read-only: no writes to user documents; P1/P2 excerpts gated by mcp_settings.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def write_cursor_mcp(config_dir: str | None = None, *, merge: bool = True) -> str:
    path = os.path.join(ROOT, ".cursor", "mcp.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = build_mcp_server_entry(config_dir=config_dir)
    data: dict = {"mcpServers": {}}
    if merge and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                data = existing
        except (OSError, json.JSONDecodeError):
            pass
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    servers["docudog"] = entry
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


def _mcp_import_ok() -> bool:
    try:
        from mcp.server.mcpserver import MCPServer  # noqa: F401
        return True
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP  # noqa: F401
            return True
        except ImportError:
            return False


def run_mcp_server(config_dir: str | None = None) -> None:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore
        except ImportError:
            print(
                "DocuDog MCP requires the 'mcp' package.\n"
                "  pip install --user \"mcp[cli]\"\n"
                "or: pip install --user -r requirements.txt",
                file=sys.stderr,
            )
            raise SystemExit(2)

    from docudog.mcp_service import McpService

    svc = McpService(config_dir)
    mcp = MCPServer(
        name="docudog",
        instructions=(
            "DocuDog local document governance corpus (read-only). "
            "Use docudog_search / docudog_get / docudog_status / docudog_thread to find "
            "already-classified local files (tags, P1–P4, summaries, related paths, threads). "
            "Do not assume raw file contents are available for sensitive levels."
        ),
    )

    @mcp.tool()
    def docudog_ping() -> str:
        """Health check: config dir, state path, excerpt policy."""
        return json.dumps(svc.ping(), ensure_ascii=False, indent=2)

    @mcp.tool()
    def docudog_status() -> str:
        """Short operational status (today counts, actions, digest)."""
        return json.dumps(svc.status(), ensure_ascii=False, indent=2)

    @mcp.tool()
    def docudog_search(
        query: str = "",
        level: str = "",
        tag: str = "",
        category_id: str = "",
        limit: int = 20,
        regex: bool = False,
    ) -> str:
        """
        Search classified DocuDog state (path/summary/tags/category).
        level: optional P1|P2|P3|P4. Not full-text of unscanned files.
        """
        return json.dumps(
            svc.search(
                query=query,
                level=level,
                tag=tag,
                category_id=category_id,
                limit=limit,
                regex=regex,
            ),
            ensure_ascii=False,
            indent=2,
        )

    @mcp.tool()
    def docudog_get(path: str = "", file_id: str = "", include_excerpt: bool = False) -> str:
        """
        One file metadata from DocuDog_state.json (path or file_id).
        include_excerpt: optional short text; blocked when security exceeds mcp_settings.
        """
        return json.dumps(
            svc.get(path, file_id=file_id, include_excerpt=include_excerpt),
            ensure_ascii=False,
            indent=2,
        )

    @mcp.tool()
    def docudog_last_classify() -> str:
        """Most recent successful classification companion JSON."""
        return json.dumps(svc.last_classify(), ensure_ascii=False, indent=2)

    @mcp.tool()
    def docudog_recent_changes(limit: int = 10) -> str:
        """Recent semantic change one-liners from state."""
        return json.dumps(
            svc.recent_changes(limit=limit), ensure_ascii=False, indent=2
        )

    @mcp.tool()
    def docudog_related(path: str, limit: int = 5) -> str:
        """Related local documents for an anchor path (lineage/summary/bundles)."""
        return json.dumps(
            svc.related(path, limit=limit), ensure_ascii=False, indent=2
        )

    @mcp.tool()
    def docudog_thread(thread_id: str = "", path: str = "", file_id: str = "") -> str:
        """One document thread (version or conversation) by id, path, or file_id."""
        return json.dumps(
            svc.thread(thread_id=thread_id, path=path, file_id=file_id),
            ensure_ascii=False,
            indent=2,
        )

    @mcp.tool()
    def docudog_by_hash(sha256: str, limit: int = 20) -> str:
        """Find classified files whose SHA-256 starts with or equals the given hex."""
        return json.dumps(svc.by_hash(sha256, limit=limit), ensure_ascii=False, indent=2)

    mcp.run(transport="stdio")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DocuDog MCP server and Cursor/Claude install helpers."
    )
    parser.add_argument(
        "--config-dir",
        default=ROOT,
        help="Directory with config.json (default: repo root)",
    )
    parser.add_argument(
        "--print-install",
        action="store_true",
        help="Print JSON install payload for Cursor and Claude Desktop",
    )
    parser.add_argument(
        "--write-cursor-mcp",
        action="store_true",
        help="Write/merge .cursor/mcp.json with docudog server entry",
    )
    args = parser.parse_args()
    cfg_dir = os.path.normpath(os.path.abspath(args.config_dir))

    if args.print_install:
        print_install(cfg_dir)
        return 0
    if args.write_cursor_mcp:
        if not _mcp_import_ok():
            print(
                "mcp package is missing; Cursor will show docudog as disconnected.\n"
                '  pip install --user "mcp[cli]"\n'
                "or: pip install --user -r requirements.txt",
                file=sys.stderr,
            )
            return 2
        path = write_cursor_mcp(cfg_dir)
        print(f"Wrote Cursor MCP config: {path}")
        print("Enable the project server 'docudog' in Cursor Settings > MCP.")
        print("Then reload MCP or start a new agent chat and call docudog_ping.")
        return 0

    run_mcp_server(cfg_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
