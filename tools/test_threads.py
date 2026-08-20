#!/usr/bin/env python3
"""Smoke tests for file_id rename + version/conversation threads."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import file_ids, threads  # noqa: E402


def _meta(sha: str, summary: str, tags: list[str], utc: str, fid: str | None = None) -> dict:
    row = {
        "sha256": sha,
        "summary": summary,
        "tags": tags,
        "security_level": "P2",
        "last_analyzed_utc": utc,
    }
    if fid:
        row["file_id"] = fid
    return row


def test_rename_adopts_id() -> None:
    td = tempfile.mkdtemp()
    old = os.path.join(td, "old.docx")
    new = os.path.join(td, "new.docx")
    files = {old: _meta("abc" * 21 + "ab", "s", [], datetime.now(timezone.utc).isoformat(), "keep-me")}
    got = file_ids.adopt_rename(files, new, files[old]["sha256"], {})
    assert got is not None and got["file_id"] == "keep-me"
    assert new in files and old not in files
    print("ok rename")


def test_live_copy_not_merged() -> None:
    td = tempfile.mkdtemp()
    a = os.path.join(td, "a.docx")
    b = os.path.join(td, "sub", "b.docx")
    os.makedirs(os.path.dirname(b), exist_ok=True)
    with open(a, "wb") as f:
        f.write(b"x")
    files = {
        a: _meta("dd" * 32, "s", [], datetime.now(timezone.utc).isoformat(), "id-a"),
    }
    got = file_ids.adopt_rename(files, b, "dd" * 32, {})
    assert got is None
    print("ok copy not merged")


def test_version_thread() -> None:
    root = tempfile.mkdtemp()
    p1 = os.path.join(root, "proj", "제안서_v1.docx")
    p2 = os.path.join(root, "proj", "제안서_최종.docx")
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "files": {
            p1: _meta("aa" * 32, "proposal budget draft", ["x"], now),
            p2: _meta("bb" * 32, "proposal budget final", ["x"], now),
        }
    }
    cfg = {
        "watch_settings": {"target_directories": [root]},
        "lineage_settings": {"clustering": "both", "similarity_threshold": 0.5},
        "thread_settings": {"include_conversations": False},
    }
    file_ids.ensure_all_file_ids(state)
    out = threads.build_threads(state, cfg)
    kinds = {t["kind"] for t in out}
    assert "version" in kinds, out
    print("ok version thread")


def test_conversation_thread() -> None:
    root = tempfile.mkdtemp()
    folder = os.path.join(root, "edge-task")
    now = datetime.now(timezone.utc).isoformat()
    ppt = os.path.join(folder, "deck.pptx")
    doc = os.path.join(folder, "brief.docx")
    state = {
        "files": {
            ppt: _meta("11" * 32, "edge deck", ["Edge AI"], now),
            doc: _meta("22" * 32, "edge brief", ["Edge AI"], now),
        }
    }
    cfg = {
        "watch_settings": {"target_directories": [root]},
        "lineage_settings": {"clustering": "filename_key"},
        "thread_settings": {"include_conversations": True, "min_rel_depth": 1},
    }
    file_ids.ensure_all_file_ids(state)
    out = threads.build_threads(state, cfg)
    kinds = {t["kind"] for t in out}
    assert "conversation" in kinds or "mixed" in kinds, out
    print("ok conversation thread")


def test_desktop_singleton_skipped() -> None:
    root = tempfile.mkdtemp()
    lone = os.path.join(root, "notes.txt")
    now = datetime.now(timezone.utc).isoformat()
    state = {"files": {lone: _meta("33" * 32, "notes", [], now)}}
    cfg = {
        "watch_settings": {"target_directories": [root]},
        "thread_settings": {"include_conversations": True},
    }
    file_ids.ensure_all_file_ids(state)
    out = threads.build_threads(state, cfg)
    assert out == []
    print("ok singleton skipped")


if __name__ == "__main__":
    test_rename_adopts_id()
    test_live_copy_not_merged()
    test_version_thread()
    test_conversation_thread()
    test_desktop_singleton_skipped()
    print("all ok")
