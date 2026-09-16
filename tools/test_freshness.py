#!/usr/bin/env python3
"""Smoke tests for latest-version resolution and stale-classification flags."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import freshness  # noqa: E402
from docudog.mcp_service import McpService  # noqa: E402


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def _service(files: dict[str, dict[str, object]]) -> McpService:
    svc = McpService(ROOT)
    svc.cfg = {"mcp_settings": {"enforce_allowlist": False}}
    svc.load_state = lambda **_kwargs: {"files": files}  # type: ignore[method-assign]
    return svc


def _write(path: str, text: str, mtime: datetime) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    stamp = mtime.timestamp()
    os.utime(path, (stamp, stamp))


def test_group_key() -> None:
    assert freshness.group_key("제안서_v1.docx") == freshness.group_key(
        "제안서_최종_진짜.docx"
    )
    assert freshness.group_key("견적서 (2).xlsx") == freshness.group_key("견적서.xlsx")
    assert freshness.group_key("plan_draft.md") == freshness.group_key("plan_final.md")
    assert freshness.group_key("plan.md") != freshness.group_key("budget.md")
    # A different extension is a different document, not another version.
    assert freshness.group_key("plan.md") != freshness.group_key("plan.docx")


def test_version_and_name_signals() -> None:
    assert freshness.version_number("보고서_v12.docx") == 12
    assert freshness.version_number("보고서 (3).docx") == 3
    assert freshness.version_number("보고서.docx") == 0
    assert freshness.name_bonus("제안서_최종.docx") > 0
    assert freshness.name_bonus("제안서_초안.docx") < 0


def main() -> int:
    test_group_key()
    test_version_and_name_signals()

    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="docudog-fresh-") as tmp:
        draft = os.path.join(tmp, "제안서_v1.docx")
        final = os.path.join(tmp, "제안서_최종_진짜.docx")
        stale = os.path.join(tmp, "견적서.xlsx")
        _write(draft, "draft", now - timedelta(days=3))
        _write(final, "final", now - timedelta(hours=1))
        _write(stale, "quote", now)

        files = {
            draft: {
                "file_id": "draft",
                "security_level": "P4",
                "tags": ["제안"],
                "summary": "제안서 초안",
                "last_analyzed_utc": _iso(now - timedelta(days=3)),
            },
            final: {
                "file_id": "final",
                "security_level": "P4",
                "tags": ["제안"],
                "summary": "제안서 최종본",
                "last_analyzed_utc": _iso(now - timedelta(hours=1)),
            },
            stale: {
                "file_id": "quote",
                "security_level": "P4",
                "tags": ["견적"],
                "summary": "견적서",
                # Analyzed long before the file was last written (NAS overwrite).
                "last_analyzed_utc": _iso(now - timedelta(days=2)),
            },
        }
        svc = _service(files)

        found = svc.search(query="제안")
        rows = {row["basename"]: row for row in found["results"]}
        assert rows["제안서_최종_진짜.docx"]["is_latest"] is True
        assert rows["제안서_v1.docx"]["is_latest"] is False
        assert rows["제안서_v1.docx"]["superseded_by"] == final
        assert rows["제안서_v1.docx"]["latest_reason"]

        latest_only = svc.search(query="제안", latest_only=True)
        assert [r["basename"] for r in latest_only["results"]] == [
            "제안서_최종_진짜.docx"
        ]
        assert latest_only["latest_only"] is True

        quote = svc.get(path=stale)
        assert quote["ok"] is True
        assert quote["stale_classification"] is True
        assert quote["file_mtime_utc"] > quote["last_analyzed_utc"]
        assert quote["file_exists"] is True
        assert rows["제안서_최종_진짜.docx"]["stale_classification"] is False

        resolved = svc.resolve("제안")
        assert resolved["ok"] is True
        assert resolved["showing"] == 1
        top = resolved["results"][0]
        assert top["path"] == final
        assert top["superseded_count"] == 1
        assert top["previous_versions"][0]["basename"] == "제안서_v1.docx"

        assert svc.resolve("제안", limit=0)["code"] == "invalid_limit"

        missing = svc.get(path=os.path.join(tmp, "없는파일.docx"))
        assert missing["ok"] is False

    print("all freshness tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
