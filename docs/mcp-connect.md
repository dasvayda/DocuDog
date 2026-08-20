# DocuDog MCP — connect guide (for humans and coding agents)

When the user says **"DocuDog을 MCP로 연결해줘"** / **"connect DocuDog MCP"**, do this — do not invent a different server.

## One-shot (Cursor, this repo)

```bash
pip install --user -r requirements.txt
python tools/docudog_mcp.py --write-cursor-mcp
```

`--write-cursor-mcp` only writes `.cursor/mcp.json`. It does not start the server.

Then in Cursor:

1. **Settings → MCP** — project server **docudog** must be **enabled** (new project servers stay off until you toggle them).
2. If status is error/disconnected, install deps: `pip install --user "mcp[cli]"` (same Python as in `mcp.json` `command`).
3. Reload MCP or start a **new** agent chat. Verify with **`docudog_ping`**.

## Print config (any client)

```bash
python tools/docudog_mcp.py --print-install
```

JSON includes:

- `cursor.mcpServers` → merge into `.cursor/mcp.json`
- `claude_desktop.mcpServers` → merge into `%APPDATA%\Claude\claude_desktop_config.json`
- Absolute `python` + `tools/docudog_mcp.py` paths for this clone

## Manual Cursor snippet

```json
{
  "mcpServers": {
    "docudog": {
      "command": "C:\\Path\\To\\python.exe",
      "args": [
        "F:\\AI-Coding-Space\\docudog\\tools\\docudog_mcp.py",
        "--config-dir",
        "F:\\AI-Coding-Space\\docudog"
      ],
      "cwd": "F:\\AI-Coding-Space\\docudog"
    }
  }
}
```

Use paths from `--print-install` (do not leave placeholders).

## Tools (read-only)

| Tool | Purpose |
|------|---------|
| `docudog_ping` | Health + state path |
| `docudog_status` | Today / actions / digest |
| `docudog_search` | Classified corpus (tags, P-level, summary) |
| `docudog_get` | One file meta (path or `file_id`, optional excerpt) |
| `docudog_thread` | Version/conversation thread by id, path, or file_id |
| `docudog_by_hash` | Files with matching SHA-256 prefix |
| `docudog_last_classify` | Latest classify companion JSON |
| `docudog_recent_changes` | Semantic change one-liners |
| `docudog_related` | Related paths for an anchor |

Not a full-disk or Cowork folder sync. DocuDog **watcher** must have classified files into `DocuDog_state.json` first. Threads/`file_id` are written when status refreshes (daemon classify or startup).

## Security defaults (`mcp_settings` in config)

- Path allowlist ≈ watch roots + output folder (`enforce_allowlist`, default true)
- Excerpt capped by `max_security_level_for_excerpt` (default **P4** = least sensitive only)
- No write tools for user documents

## Agent checklist

1. `python tools/docudog_mcp.py --write-cursor-mcp` (or merge `--print-install` JSON)
2. Confirm `mcp` package installed (`pip install --user "mcp[cli]"`)
3. Toggle project MCP **docudog** on in Cursor Settings
4. Call `docudog_ping`
4. If state missing, tell user to run `main.py` / classify once — MCP does not invent files

See also: [docudog-output-spec.md](docudog-output-spec.md), backlog `260805-01` in [to-do-list.md](../to-do-list.md).
