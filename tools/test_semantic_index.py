#!/usr/bin/env python3
"""Offline smoke for optional Zvec semantic index lifecycle and MCP gating."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import semantic_index  # noqa: E402
from docudog.mcp_service import McpService  # noqa: E402


def _config(root: str) -> dict:
    return {
        "semantic_search": {
            "enabled": True,
            "index_path": root,
            "indexed_levels": ["P3", "P4"],
            "max_security_level_for_result": "P4",
            "chunk_max_chars": 120,
            "max_chunks_per_document": 10,
            "max_result_chars": 80,
            "embedding_provider": "hashing",  # offline test provider
        },
        "mcp_settings": {
            "enforce_allowlist": False,
            "max_security_level_for_excerpt": "P4",
        },
    }


def _meta(file_id: str, digest: str, level: str) -> dict:
    return {
        "file_id": file_id,
        "sha256": digest,
        "security_level": level,
        "tags": ["contract"],
        "category_ids": ["legal"],
        "last_analyzed_utc": "2026-09-07T00:00:00+00:00",
    }


def main() -> int:
    disabled_root = tempfile.mkdtemp(prefix="docudog-semantic-disabled-")
    try:
        disabled_cfg = {"semantic_search": {"enabled": False, "index_path": disabled_root}}
        assert semantic_index.upsert_file(
            disabled_cfg,
            path="unused.txt",
            text="this must not create an index",
            metadata=_meta("disabled", "0" * 64, "P4"),
        )["reason"] == "disabled"
        assert not os.path.exists(os.path.join(disabled_root, "zvec"))
        disabled_svc = McpService(ROOT)
        disabled_svc.cfg = disabled_cfg
        assert disabled_svc.semantic_search("unused")["code"] == "semantic_search_disabled"
    finally:
        shutil.rmtree(disabled_root, ignore_errors=True)
    try:
        import zvec  # noqa: F401
    except ImportError:
        print("semantic index smoke skipped: install requirements-semantic.txt")
        return 0
    root = tempfile.mkdtemp(prefix="docudog-semantic-")
    try:
        cfg = _config(root)
        p4 = os.path.join(root, "public-contract.txt")
        p3 = os.path.join(root, "internal-contract.txt")
        first = semantic_index.upsert_file(
            cfg,
            path=p4,
            text="Renewal clause: the contract extends automatically each year.",
            metadata=_meta("p4-file", "a" * 64, "P4"),
        )
        assert first["indexed"] is True
        semantic_index.upsert_file(
            cfg,
            path=p3,
            text="Internal contract strategy and renewal approval notes.",
            metadata=_meta("p3-file", "b" * 64, "P3"),
        )
        raw = semantic_index.search(cfg, "contract renewal", limit=10)
        assert raw["ok"] is True
        assert raw["results"] and raw["results"][0]["path"] == p4
        assert all(row["security_level"] == "P4" for row in raw["results"])

        updated = semantic_index.upsert_file(
            cfg,
            path=p4,
            text="Termination clause: either party may end the agreement.",
            metadata=_meta("p4-file", "c" * 64, "P4"),
        )
        assert updated["reason"] == "updated"
        after = semantic_index.search(cfg, "termination agreement", limit=10)
        assert any(row["path"] == p4 for row in after["results"])

        svc = McpService(ROOT)
        svc.cfg = cfg
        gated = svc.semantic_search("contract", limit=10)
        assert gated["ok"] is True
        assert all(row["security_level"] == "P4" for row in gated["results"])
        assert semantic_index.remove_file(cfg, p4) is True
        print("semantic index smoke passed")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
