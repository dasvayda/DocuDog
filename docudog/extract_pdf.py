"""PDF text-layer extraction (no OCR)."""

from __future__ import annotations


class EncryptedPdfError(Exception):
    """Password-protected PDF."""


class EmptyPdfTextError(Exception):
    """No extractable text (likely scan/image-only)."""


def read_pdf_text(path: str, *, max_pages: int = 40) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("pypdf가 없습니다. pip install pypdf") from e

    try:
        reader = PdfReader(path)
    except Exception as e:
        raise ValueError(f"PDF를 열 수 없음: {e}") from e

    if getattr(reader, "is_encrypted", False):
        try:
            ok = reader.decrypt("")
        except Exception as e:
            raise EncryptedPdfError("암호화된 PDF는 본문 추출 불가") from e
        if not ok:
            raise EncryptedPdfError("암호화된 PDF는 본문 추출 불가")

    parts: list[str] = []
    pages = list(reader.pages)[: max(1, max_pages)]
    for page in pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        t = t.strip()
        if t:
            parts.append(t)
    text = "\n".join(parts).strip()
    if not text:
        raise EmptyPdfTextError("PDF 텍스트 레이어가 비어 있음 (스캔본 가능)")
    return text
