"""Append-only markdown audit timeline for classifications (+ sibling HTML)."""

from __future__ import annotations

import html
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Iterable

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

_REAL_BACKEND_SOURCES = frozenset({"lite_rt", "lm_studio", "openai_compatible"})

_FOOTER_PATTERN = re.compile(
    r"\r?\n<!-- docudog-meta:start -->.*?\r?\n<!-- docudog-meta:end -->\r?\n?",
    re.DOTALL,
)

_MD_INLINE = re.compile(
    r"`([^`]+)`|\*\*([^*]+)\*\*|_([^_]+)_"
)


def _split_report_core_and_trailing(body: str) -> tuple[str, str]:
    """
    Remove at most one docudog footer block; return (core, text_that_was_after_footer).
    Preserves append_note lines that were written after the footer.
    """
    m = _FOOTER_PATTERN.search(body)
    if not m:
        return body.rstrip() + "\n", ""
    core = body[: m.start()].rstrip() + "\n"
    trailing = body[m.end() :].lstrip("\r\n")
    return core, trailing


def _expand(path: str) -> str:
    return os.path.normpath(os.path.expandvars(path))


def html_path_for_report(report_path: str) -> str:
    """Same basename as the markdown report, ``.html`` extension."""
    path = _expand(report_path)
    root, _ext = os.path.splitext(path)
    return root + ".html"


def _sanitize_cell(value: str) -> str:
    """Keep table rows on one line; avoid breaking pipe tables."""
    return " ".join(value.replace("|", "\\|").split())


def _report_has_inference_column(report_path: str) -> bool:
    """기존 리포트(6열)와 호환: Inference 열이 없으면 새 열 없이 append."""
    if not os.path.isfile(report_path):
        return True
    try:
        with open(report_path, encoding="utf-8") as f:
            head = f.read(8000)
    except OSError:
        return True
    return "| Inference |" in head


def _format_report_timestamp(dt: datetime) -> str:
    """
    표시용 시각: 저장은 UTC로 해도 리포트에는 OS 로컬(한국 PC면 KST)으로 변환.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    wall = local.strftime("%Y-%m-%d %H:%M:%S")
    tz_name = local.tzname()
    if tz_name and tz_name != "UTC":
        return f"{wall} {tz_name}"
    # 일부 환경에서 tzname 비어 있음 → 숫자 오프셋
    off = local.strftime("%z")
    if off:
        return f"{wall} (UTC{off[:3]}:{off[3:]})"
    return wall


def _last_inference_footer_md(inference_source: str, analyzed_at_utc: datetime) -> str:
    """Single-line markdown footer; replaced on each successful classification append."""
    ts = _format_report_timestamp(analyzed_at_utc)
    src = _sanitize_cell(str(inference_source).strip() or "unknown")
    return (
        "\n<!-- docudog-meta:start -->\n\n"
        f"_Last inference: `{src}` · {ts}_\n\n"
        "<!-- docudog-meta:end -->\n"
    )


def _inline_md_to_html(text: str) -> str:
    """Escape then apply a tiny subset: `code`, **bold**, _italic_."""

    def repl(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            return f"<code>{html.escape(m.group(1))}</code>"
        if m.group(2) is not None:
            return f"<strong>{html.escape(m.group(2))}</strong>"
        return f"<em>{html.escape(m.group(3))}</em>"

    parts: list[str] = []
    pos = 0
    for m in _MD_INLINE.finditer(text):
        parts.append(html.escape(text[pos : m.start()]))
        parts.append(repl(m))
        pos = m.end()
    parts.append(html.escape(text[pos:]))
    return "".join(parts)


def _split_md_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_md_table_sep(line: str) -> bool:
    cells = _split_md_table_row(line)
    if not cells:
        return False
    return all(
        re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) is not None for c in cells
    )


def markdown_report_to_html(
    md_body: str, *, title: str = "DocuDog classification report"
) -> str:
    """Convert DocuDog report markdown (tables, notes, light inline) to a standalone HTML page."""
    lines = md_body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    body_parts: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            i += 1
            continue
        if stripped.startswith("# "):
            body_parts.append(f"<h1>{_inline_md_to_html(stripped[2:].strip())}</h1>")
            i += 1
            continue
        if stripped.startswith("> "):
            note_lines = [stripped[2:]]
            i += 1
            while i < n and lines[i].strip().startswith("> "):
                note_lines.append(lines[i].strip()[2:])
                i += 1
            inner = "<br>\n".join(_inline_md_to_html(x) for x in note_lines)
            body_parts.append(f'<blockquote class="note">{inner}</blockquote>')
            continue
        if stripped.startswith("|"):
            table_lines = [stripped]
            i += 1
            while i < n and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            if len(table_lines) >= 2 and _is_md_table_sep(table_lines[1]):
                headers = _split_md_table_row(table_lines[0])
                rows = [_split_md_table_row(r) for r in table_lines[2:]]
            else:
                headers = _split_md_table_row(table_lines[0])
                rows = [_split_md_table_row(r) for r in table_lines[1:]]
            thead = "".join(f"<th>{_inline_md_to_html(h)}</th>" for h in headers)
            tbody_rows: list[str] = []
            for row in rows:
                cells = (row + [""] * len(headers))[: len(headers)]
                tbody_rows.append(
                    "<tr>"
                    + "".join(f"<td>{_inline_md_to_html(c)}</td>" for c in cells)
                    + "</tr>"
                )
            body_parts.append(
                '<div class="table-wrap"><table>\n'
                f"<thead><tr>{thead}</tr></thead>\n"
                f"<tbody>\n{chr(10).join(tbody_rows)}\n</tbody>\n"
                "</table></div>"
            )
            continue
        body_parts.append(f"<p>{_inline_md_to_html(stripped)}</p>")
        i += 1

    content = "\n".join(body_parts) if body_parts else "<p><em>(empty report)</em></p>"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ko">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        "<style>\n"
        ":root {\n"
        "  --bg: #f7f4ef;\n"
        "  --ink: #1c1917;\n"
        "  --muted: #57534e;\n"
        "  --line: #d6d3d1;\n"
        "  --card: #fffdf9;\n"
        "  --accent: #0f766e;\n"
        "  --note: #fff7ed;\n"
        "  --note-border: #fdba74;\n"
        "}\n"
        "* { box-sizing: border-box; }\n"
        "body {\n"
        "  margin: 0;\n"
        "  font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;\n"
        "  color: var(--ink);\n"
        "  background:\n"
        "    radial-gradient(1200px 500px at 10% -10%, #ccfbf1 0%, transparent 55%),\n"
        "    radial-gradient(900px 400px at 100% 0%, #ffedd5 0%, transparent 50%),\n"
        "    var(--bg);\n"
        "  line-height: 1.5;\n"
        "}\n"
        "main {\n"
        "  max-width: 1100px;\n"
        "  margin: 0 auto;\n"
        "  padding: 2rem 1.25rem 3rem;\n"
        "}\n"
        "h1 { font-size: 1.6rem; margin: 0 0 0.75rem; letter-spacing: -0.02em; }\n"
        "p { color: var(--muted); margin: 0.5rem 0 1rem; }\n"
        ".table-wrap {\n"
        "  overflow-x: auto;\n"
        "  background: var(--card);\n"
        "  border: 1px solid var(--line);\n"
        "  border-radius: 10px;\n"
        "  margin: 1rem 0 1.5rem;\n"
        "}\n"
        "table { border-collapse: collapse; width: 100%; font-size: 0.92rem; }\n"
        "th, td {\n"
        "  text-align: left;\n"
        "  vertical-align: top;\n"
        "  padding: 0.65rem 0.75rem;\n"
        "  border-bottom: 1px solid var(--line);\n"
        "}\n"
        "th {\n"
        "  background: #ecfdf5;\n"
        "  color: var(--accent);\n"
        "  font-weight: 600;\n"
        "  white-space: nowrap;\n"
        "}\n"
        "tr:last-child td { border-bottom: none; }\n"
        "code {\n"
        "  font-family: Consolas, 'Courier New', monospace;\n"
        "  font-size: 0.86em;\n"
        "  background: #f5f5f4;\n"
        "  padding: 0.1em 0.35em;\n"
        "  border-radius: 4px;\n"
        "}\n"
        "blockquote.note {\n"
        "  margin: 0.5rem 0;\n"
        "  padding: 0.65rem 0.85rem;\n"
        "  background: var(--note);\n"
        "  border-left: 4px solid var(--note-border);\n"
        "  color: #7c2d12;\n"
        "  font-size: 0.92rem;\n"
        "  word-break: break-word;\n"
        "}\n"
        "em { color: var(--muted); }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"<main>\n{content}\n</main>\n"
        "</body>\n"
        "</html>\n"
    )


def sync_report_html(report_path: str) -> str | None:
    """
    Rewrite sibling ``*.html`` from the markdown report (same basename).
    Returns the HTML path, or None if the markdown file is missing.
    """
    md_path = _expand(report_path)
    if not os.path.isfile(md_path):
        return None
    html_path = html_path_for_report(md_path)
    try:
        with open(md_path, encoding="utf-8") as f:
            md_body = f.read()
        title = os.path.splitext(os.path.basename(md_path))[0] or "DocuDog report"
        page = markdown_report_to_html(md_body, title=title)
        os.makedirs(os.path.dirname(html_path) or ".", exist_ok=True)
        with open(html_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(page)
    except OSError as e:
        logger.warning("HTML report sync failed (%s): %s", html_path, e)
        return None
    logger.debug("Synced HTML report: %s", html_path)
    return html_path


def append_classification(
    report_path: str,
    analyzed_at_utc: datetime,
    file_name: str,
    file_hash: str,
    tags: Iterable[str],
    security_level: str,
    summary: str,
    inference_source: str = "mock",
    inference_reason: str = "",
    owner_tags_applied: bool = False,
    config: dict | None = None,
    state: dict | None = None,
) -> None:
    """Append one markdown table row to the report (creates file + header if needed)."""
    from .security_labels import format_security_level

    path = _expand(report_path)

    tags_joined = ", ".join(tags)
    time_str = _format_report_timestamp(analyzed_at_utc)
    summary_one_line = _sanitize_cell(summary.replace("\r\n", "\n").replace("\n", " / "))
    sec_display = format_security_level(security_level, config)
    infer_real = inference_source in _REAL_BACKEND_SOURCES

    use_infer_col = _report_has_inference_column(path)
    if infer_real and owner_tags_applied:
        if inference_reason:
            infer_cell = f"{inference_source} + owner ({_sanitize_cell(inference_reason)})"
        else:
            infer_cell = f"{inference_source} + owner tags"
    elif infer_real and inference_reason:
        infer_cell = f"{inference_source} ({_sanitize_cell(inference_reason)})"
    elif infer_real:
        infer_cell = inference_source
    elif inference_reason:
        infer_cell = f"mock ({_sanitize_cell(inference_reason)[:56]})"
    else:
        infer_cell = "mock"

    if use_infer_col:
        row = (
            f"| {time_str} | {_sanitize_cell(file_name)} | `{file_hash}` | "
            f"{_sanitize_cell(tags_joined)} | {_sanitize_cell(sec_display)} | {_sanitize_cell(infer_cell)} | "
            f"{summary_one_line} |\n"
        )
        header = (
            "# DocuDog classification report\n\n"
            "로컬 누적 감사 로그. **Security** 열: 사람용 라벨 + `(P1)`~`(P4)`. "
            "**Inference** 열: `lite_rt` = LiteRT-LM, "
            "`lm_studio` / `openai_compatible` = 로컬/원격 chat API, "
            "`mock` = 모의 결과. `+ owner` = `DocuDog_tag_overrides.json` 적용. "
            "등급은 모델 판단이라 backend에 따라 흔들릴 수 있음.\n\n"
            "| Analyzed At (local) | File | SHA-256 | Tags | Security | Inference | Summary |\n"
            "|---|---|---|---|---|---|---|\n"
        )
    else:
        row = (
            f"| {time_str} | {_sanitize_cell(file_name)} | `{file_hash}` | "
            f"{_sanitize_cell(tags_joined)} | {_sanitize_cell(sec_display)} | {summary_one_line} |\n"
        )
        header = (
            "# DocuDog classification report\n\n"
            "로컬 누적 감사 로그 (네트워크 전송 없음).\n\n"
            "| Analyzed At (local) | File | SHA-256 | Tags | Security | Summary |\n"
            "|---|---|---|---|---|---|\n"
        )

    footer = _last_inference_footer_md(inference_source, analyzed_at_utc)
    with _write_lock:
        path = _expand(report_path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        is_new = not os.path.isfile(path)
        if is_new:
            body = header + row + footer
            if state is not None:
                from . import skip_insights

                body = skip_insights.upsert_report_banner(body, state)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
        else:
            try:
                with open(path, encoding="utf-8") as f:
                    body = f.read()
            except OSError as e:
                logger.warning("Report read failed for footer update (%s): %s", path, e)
                with open(path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(row)
                    f.write(footer)
            else:
                core, trailing = _split_report_core_and_trailing(body)
                new_body = core + row + footer
                if trailing:
                    new_body = new_body.rstrip() + "\n\n" + trailing
                if not new_body.endswith("\n"):
                    new_body += "\n"
                if state is not None:
                    from . import skip_insights

                    new_body = skip_insights.upsert_report_banner(new_body, state)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_body)
        sync_report_html(path)
    logger.debug("Appended report row for %s", file_name)


def refresh_report_banner(report_path: str, state: dict) -> None:
    """Rewrite blind-spot banner in an existing report (best-effort)."""
    from . import skip_insights

    path = _expand(report_path)
    if not os.path.isfile(path):
        return
    with _write_lock:
        try:
            with open(path, encoding="utf-8") as f:
                body = f.read()
            new_body = skip_insights.upsert_report_banner(body, state)
            if new_body != body:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_body)
                sync_report_html(path)
        except OSError as e:
            logger.warning("Report banner refresh failed (%s): %s", path, e)


def append_note(report_path: str, message: str) -> None:
    """Append a plain note line (e.g., skipped formats) for traceability."""
    path = _expand(report_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = _format_report_timestamp(datetime.now(timezone.utc))
    line = f"\n> [{ts}] {message}\n"
    with _write_lock:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
        sync_report_html(path)
