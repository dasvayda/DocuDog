"""Hangul HWP/HWPX body-text extraction for LLM classification.

``reference/hop`` (https://github.com/golbin/hop) is a Tauri desktop app on
``rhwp`` (Rust/WASM). DocuDog only needs plain text, so we import ``syhwp``
(pure Python, MIT, ``olefile``) the same way we import ``python-docx``.
Parser fixes then come from ``pip install -U syhwp`` instead of vendoring hop.
"""

from __future__ import annotations


class EncryptedHwpError(Exception):
    """Password-protected or distribution (copy-protected) HWP body."""


def read_hwp_text(path: str) -> str:
    """Return body text (paragraphs + table cells) from ``.hwp`` or ``.hwpx``."""
    try:
        import syhwp  # type: ignore[import-untyped]
    except ImportError as e:
        raise ValueError("syhwp가 없습니다. pip install syhwp") from e

    try:
        text = syhwp.extract_text(path) or ""
    except syhwp.EncryptedDocumentError as e:
        raise EncryptedHwpError(
            "암호화/배포용 HWP는 본문 추출 불가"
        ) from e
    except syhwp.UnsupportedFormatError as e:
        raise ValueError(f"지원되지 않는 HWP 형식: {e}") from e
    except syhwp.InvalidHwpError as e:
        raise ValueError(f"손상되었거나 읽을 수 없는 HWP: {e}") from e
    except syhwp.SyhwpError as e:
        raise ValueError(f"HWP 텍스트 추출 실패: {e}") from e
    return text.strip()
