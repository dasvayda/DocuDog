#!/usr/bin/env python3
"""Smoke: extract text from a tiny generated PDF."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog.extract_pdf import EmptyPdfTextError, read_pdf_text  # noqa: E402


def main() -> int:
    from pypdf import PdfWriter

    fd, blank = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        w = PdfWriter()
        w.add_blank_page(width=72, height=72)
        with open(blank, "wb") as f:
            w.write(f)
        try:
            read_pdf_text(blank)
            print("expected empty pdf skip")
            return 1
        except EmptyPdfTextError:
            print("ok empty/scan skip")
    finally:
        try:
            os.remove(blank)
        except OSError:
            pass

    # text-bearing PDF via a well-known minimal stream
    fd, filled = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        # Standard one-page Hello PDF
        body = b"""%PDF-1.1
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 44 >>stream
BT /F1 12 Tf 20 150 Td (DocuDog PDF) Tj ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000360 00000 n 
trailer<< /Size 6 /Root 1 0 R >>
startxref
429
%%EOF
"""
        with open(filled, "wb") as f:
            f.write(body)
        text = read_pdf_text(filled)
        if "DocuDog" not in text and "PDF" not in text:
            print("unexpected text:", repr(text))
            return 1
        print("ok text pdf:", text.replace("\n", " ")[:80])

        fixture = os.path.join(ROOT, "fixtures", "pdf_hello.pdf")
        if os.path.isfile(fixture):
            t2 = read_pdf_text(fixture)
            if "DocuDog" not in t2 and "PDF" not in t2:
                print("fixture unexpected:", repr(t2))
                return 1
            print("ok fixture pdf")
    finally:
        try:
            os.remove(filled)
        except OSError:
            pass
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
