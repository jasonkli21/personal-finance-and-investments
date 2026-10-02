"""Resource-limited text extraction subprocess for uploaded PDFs."""

from __future__ import annotations

import importlib
import io
import json
import os
import sys

MAX_PDF_BYTES = 20_000_000
MAX_PAGES = int(os.environ.get("PDF_MAX_PAGES", "100"))
MAX_PAGE_TEXT = 200_000
MAX_DOCUMENT_TEXT = 2_000_000


def _apply_process_limits() -> None:
    if os.name != "posix":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (6, 7))
    if hasattr(resource, "RLIMIT_AS"):
        memory_limit = 768 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
    if hasattr(resource, "RLIMIT_FSIZE"):
        resource.setrlimit(resource.RLIMIT_FSIZE, (4_000_000, 4_000_000))
    if hasattr(resource, "RLIMIT_CORE"):
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main() -> None:
    _apply_process_limits()
    result: dict[str, object]
    try:
        content = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
        if not content.startswith(b"%PDF-") or len(content) > MAX_PDF_BYTES:
            raise ValueError("pdf_invalid")
        PdfReader = importlib.import_module("pypdf").PdfReader
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PAGES:
            raise ValueError("pdf_unsupported")
        pages: list[dict[str, object]] = []
        total_chars = 0
        for number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text(extraction_mode="layout") or ""
            if len(page_text) > MAX_PAGE_TEXT:
                raise ValueError("pdf_page_limit")
            total_chars += len(page_text)
            if total_chars > MAX_DOCUMENT_TEXT:
                raise ValueError("pdf_text_limit")
            pages.append({"page": number, "text": page_text})
        result = {"pages": pages}
    except ValueError as exc:
        code = str(exc) if str(exc).startswith("pdf_") else "pdf_invalid"
        result = {"error": code}
    except BaseException:  # noqa: BLE001 - do not leak parser internals or content
        result = {"error": "pdf_unreadable"}
    sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
