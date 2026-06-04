#!/usr/bin/env python3
"""Smoke-test DocuDog core without 120s idle: mock LLM + reporter + router helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# Project root (parent of tools/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import inference  # noqa: E402
from docudog import reporter  # noqa: E402
from docudog import router  # noqa: E402


def main() -> int:
    cfg_path = os.path.join(ROOT, "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["model"]["use_mock"] = True
    cfg["model"]["litert_lm_bundle_path"] = ""

    sample = (
        "DocuDog quick test document.\n"
        "This paragraph exists only to exceed minimum byte filters in config.\n"
        * 30
    )
    sample = sample.encode("utf-8")
    if len(sample) < 1024:
        sample = sample + b"x" * (1024 - len(sample))

    fd, txt_path = tempfile.mkstemp(suffix=".txt", prefix="docudog_test_")
    os.write(fd, sample)
    os.close(fd)
    txt_path = os.path.normpath(txt_path)

    try:
        text, reason = router.extract_document_text(txt_path)
        assert reason is None and text
        digest = router.sha256_file(txt_path)
        assert len(digest) == 64

        out = dict(inference.classify_document(text, cfg, should_yield=None))
        inf_src = out.pop(inference.DOCUDOG_META_SOURCE, "mock")
        inf_reason = out.pop(inference.DOCUDOG_META_REASON, "")
        assert isinstance(out.get("tags"), list)
        assert out.get("security_level")

        fd2, report_path = tempfile.mkstemp(suffix=".md", prefix="docudog_report_")
        os.close(fd2)
        report_path = os.path.normpath(report_path)

        reporter.append_classification(
            report_path,
            datetime.now(timezone.utc),
            os.path.basename(txt_path),
            digest,
            out["tags"],
            str(out["security_level"]),
            str(out.get("summary", "")),
            inference_source=inf_src,
            inference_reason=inf_reason,
        )
        with open(report_path, encoding="utf-8") as rf:
            body = rf.read()
        assert "|" in body

        print("quick_test: OK")
        print("  sample file:", txt_path)
        print("  report:", report_path)
        print("  mock tags:", out.get("tags"))
        return 0
    finally:
        try:
            os.unlink(txt_path)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
