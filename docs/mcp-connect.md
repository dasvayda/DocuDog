# DocuDog MCP — connect guide (for humans and coding agents)

When the user says **"DocuDog을 MCP로 연결해줘"** / **"connect DocuDog MCP"**, do this — do not invent a different server.

## One-shot (Cursor, this repo)

```bash
pip install --user -r requirements.txt
python tools/docudog_mcp.py --write-all-mcp
```

`--write-cursor-mcp` / `--write-claude-desktop-mcp` / `--write-all-mcp` only write JSON. They do not start the server. No npm. The default remains local stdio.

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
| `docudog_search` | Corpus search; optional `since`/`until` UTC dates; page with `offset` or returned `cursor`; `latest_only: true` hides superseded copies |
| `docudog_resolve` | "Latest <topic>" in one call: latest copies plus the versions they replace and why |
| `docudog_semantic_search` | Optional local Zvec full-text + semantic chunk search. Requires `requirements-semantic.txt`, `semantic_search.enabled: true`, and an index rebuild or later classification. |
| `docudog_get` | One file meta (path or `file_id`, optional excerpt) |
| `docudog_get_lineage` | Latest version in a thread + member timeline |
| `docudog_get_context_bundle` | Related paths + time-window bundles |
| `docudog_thread` | Version/conversation thread by id, path, or file_id |
| `docudog_by_hash` | Files with matching SHA-256 prefix |
| `docudog_last_classify` | Latest classify companion JSON |
| `docudog_recent_changes` | Semantic change one-liners |
| `docudog_related` | Related paths for an anchor |

Not a full-disk or Cowork folder sync. DocuDog **watcher** must have classified files into `DocuDog_state.json` first. Threads/`file_id` are written when status refreshes (daemon classify or startup).

## Freshness fields (`freshness_settings`, on by default)

`docudog_search` / `docudog_resolve` / `docudog_get` / `docudog_semantic_search` rows carry:

| Field | Meaning for the answer |
|-------|------------------------|
| `is_latest` | `false` means a newer copy of the same document exists — quote the newer one |
| `superseded_by` | Absolute path of that newer copy |
| `latest_reason` | One line for why it won (disk mtime, `_최종` style token, version number) |
| `file_mtime_utc` vs `last_analyzed_utc` | Disk write time vs the time DocuDog classified it |
| `stale_classification` | `true` when the file was written after classification (shared folder / NAS overwrite). Say the summary and P level may be out of date. |
| `file_exists` | `false` means the path is gone; the record is a past snapshot |

`stale_skew_seconds` (default 60) absorbs clock/filesystem skew. DocuDog does not
rename files to mark a final version, and it does not sync shared folders between
PCs — it only reports what the timestamps say.

## Security defaults (`mcp_settings` in config)

- Path allowlist ≈ watch roots + output folder (`enforce_allowlist`, default true)
- Excerpt capped by `max_security_level_for_excerpt` (default **P4** = least sensitive only)
- P1/P2 excerpt denial uses `code`: `excerpt_blocked_p1`. Do not re-ask for original text.
- Tool errors always return `ok: false`, a stable machine-readable `code`, and a human-readable `error`.
- Search pagination is zero-based: send `offset`, or send the opaque `next_cursor` returned by the previous page. Do not send both.
- No write tools for user documents

## Optional remote MCP for Cowork / ChatGPT

The remote gateway is opt-in and disabled by default. It exposes the same
read-only tools through MCP Streamable HTTP; it does not upload the Zvec index
or open a document directory by itself.

1. Install the current MCP runtime: `pip install --upgrade "mcp[cli]>=2.1.0"`.
2. Copy the `remote_mcp_settings` example into the YAML overlay and set
   `enabled: true` while keeping `host: 127.0.0.1`.
3. Create a random secret outside the repository, for example
   `setx DOCUDOG_REMOTE_MCP_TOKEN "<random-32-byte-token>"`, then restart the shell.
4. Start it explicitly: `python tools/docudog_mcp.py --remote`.
5. Connect a trusted tunnel or TLS reverse proxy to `http://127.0.0.1:8765/mcp`
   and configure its Bearer token. Do not expose the local port directly.

Non-loopback binding is rejected unless `allow_nonlocal_bind: true` and an
explicit `allowed_hosts` list are present. The server also validates Host and
Origin headers to reduce DNS-rebinding risk. Remote clients receive only the
same allowlist, security-level, and excerpt-policy filtered results as local
MCP clients. Disable it by setting `enabled: false` and stopping the process.

ChatGPT and Cowork use remote connectors; they cannot launch this local stdio
process directly. Use a provider-supported secure tunnel or authenticated TLS
gateway when connecting them.

## Optional local semantic search

This is disabled by default, so it does not add an embedding model download or
index to ordinary DocuDog installs. To enable it, install the optional packages,
set `semantic_search.enabled: true` in the YAML overlay, then build the local
index from files already classified by DocuDog:

```bash
pip install -r requirements-semantic.txt
python tools/rebuild_semantic_index.py
```

The default local model is `intfloat/multilingual-e5-small`. Its initial model
download is local-model setup only; document text and queries are not sent to a
remote embedding provider. P1/P2 body chunks are not indexed by default, and
MCP applies the existing allowlist and excerpt policy again before returning a
result.

## Agent checklist

1. `python tools/docudog_mcp.py --write-all-mcp` (or `--write-cursor-mcp`)
2. Confirm `mcp` package installed (`pip install --user "mcp[cli]"`)
3. Toggle project MCP **docudog** on in Cursor Settings
4. Call `docudog_ping`
4. If state missing, tell user to run `main.py` / classify once — MCP does not invent files

See also: [docudog-output-spec.md](docudog-output-spec.md), backlog `260805-01` in [to-do-list.md](../to-do-list.md).
