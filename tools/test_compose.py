#!/usr/bin/env python3
"""Compose engine + artifact skip + operator host guard smokes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import artifact_home, compose, file_filters, operator_http, status_dashboard  # noqa: E402
from docudog import runtime_pause  # noqa: E402


def _state_for(paths: dict[str, dict]) -> dict:
    files = {}
    for i, (path, extra) in enumerate(paths.items(), start=1):
        meta = {
            "file_id": f"fid-{i:04d}",
            "sha256": f"sha{i}",
            "last_analyzed_utc": "2026-09-15T00:00:00+00:00",
            "summary": extra.get("summary", f"summary {i}"),
            "tags": extra.get("tags", ["test"]),
            "security_level": extra.get("security_level", "P4"),
        }
        files[path] = meta
    return {"version": 1, "files": files, "last_inference_backend": "mock", "threads": []}


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        home = tmp / ".docudog"
        home.mkdir()
        watch = tmp / "watch"
        watch.mkdir()
        a = watch / "견적_최종.txt"
        b = watch / "단가.txt"
        c = watch / "메모_초안.txt"
        p1 = watch / "주민_초안.txt"
        a.write_text("final quote body ALPHA_UNIQUE", encoding="utf-8")
        b.write_text("price table BRAVO_UNIQUE", encoding="utf-8")
        c.write_text("old draft CHARLIE_UNIQUE", encoding="utf-8")
        p1.write_text("secret SECRET_P1_UNIQUE 주민번호", encoding="utf-8")
        cfg = {
            "paths": {"artifact_home": str(home)},
            "model": {"use_mock": True},
            "compose_settings": {"max_sources": 8, "allow_p1_body": False},
            "file_filters": {"allowed_extensions": [".txt", ".md"], "size_limit": {"min_bytes": 1}},
        }
        state = _state_for(
            {
                str(a): {"summary": "견적 최신", "security_level": "P4"},
                str(b): {"summary": "단가표", "security_level": "P4"},
                str(c): {"summary": "초안 메모", "security_level": "P4"},
                str(p1): {"summary": "민감 메모", "security_level": "P1"},
            }
        )

        md_status = status_dashboard.build_status_markdown(cfg, state, str(home / "classification_report.md"))
        assert "## 건강" in md_status, md_status[:400]
        assert "연습 모드" in md_status
        assert "주민_초안.txt" in md_status
        assert "SECRET_P1_UNIQUE" not in md_status

        r = compose.compose(
            cfg,
            state,
            kind="brief",
            intent="임원용 한 장",
            file_ids_selected=["fid-0001", "fid-0002", "fid-0004"],
            formats=["md", "html", "docx"],
            report_path=str(home / "classification_report.md"),
        )
        assert r["ok"], r
        md_path = r["paths"]["md"]
        assert md_path.startswith(str(home / "composed")), md_path
        text = Path(md_path).read_text(encoding="utf-8")
        assert "원본을 대체하지 않음" in text
        assert str(a) in text
        assert "ALPHA_UNIQUE" in text
        assert "SECRET_P1_UNIQUE" not in text
        assert "본문 생략" in text or "민감" in text
        html_p = r["paths"].get("html")
        assert html_p and Path(html_p).is_file()
        docx_p = r["paths"].get("docx")
        try:
            import docx  # noqa: F401
        except ImportError:
            docx = None  # type: ignore[assignment]
        if docx is not None:
            assert docx_p and Path(docx_p).is_file(), r["paths"]
        assert not file_filters.passes_file_filters(cfg, md_path)

        h = compose.compose(
            cfg,
            state,
            kind="handover",
            intent="후임 OJT",
            file_ids_selected=["fid-0001", "fid-0002", "fid-0003"],
            formats=["md"],
            report_path=str(home / "classification_report.md"),
        )
        assert h["ok"], h
        ht = Path(h["paths"]["md"]).read_text(encoding="utf-8")
        for heading in ("## 개요", "## 읽는 순서", "## 문서 목록", "## 공백"):
            assert heading in ht, heading
        # draft should not be the only "지금 볼 파일"
        overview = ht.split("## 읽는 순서")[0]
        assert "견적_최종.txt" in overview or "견적_최종" in overview

        too = compose.compose(
            cfg,
            state,
            kind="brief",
            intent="x",
            file_ids_selected=[],
            formats=["md"],
        )
        assert not too["ok"]

        runtime_pause.set_paused(False)
        class Dummy:
            headers = {"Host": "evil.example:8766"}
            client_address = ("8.8.8.8", 1)

        assert not operator_http._host_ok(Dummy(), 8766)  # type: ignore[arg-type]
        Dummy.headers = {"Host": "127.0.0.1:8766"}
        Dummy.client_address = ("127.0.0.1", 1)
        assert operator_http._host_ok(Dummy(), 8766)  # type: ignore[arg-type]

        assert artifact_home.path_is_artifact(cfg, md_path)

    print("test_compose: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
