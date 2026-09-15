"""Loopback-only operator page: status, pause, compose. Not a document library."""

from __future__ import annotations

import html
import json
import logging
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import artifact_home, compose, runtime_pause, status_dashboard
from .security_labels import format_security_level

logger = logging.getLogger(__name__)

_httpd: ThreadingHTTPServer | None = None
_httpd_lock = threading.Lock()
_cfg: dict[str, Any] = {}
_config_dir = ""


def dashboard_settings(cfg: dict[str, Any] | None) -> dict[str, Any]:
    raw = (cfg or {}).get("dashboard_settings")
    block = raw if isinstance(raw, dict) else {}
    enabled = True if "enabled" not in block else bool(block.get("enabled"))
    try:
        port = int(block.get("port", 8766))
    except (TypeError, ValueError):
        port = 8766
    return {"enabled": enabled, "port": max(1024, min(65535, port))}


def operator_url(cfg: dict[str, Any] | None) -> str:
    port = dashboard_settings(cfg)["port"]
    return f"http://127.0.0.1:{port}/"


def _load_state(cfg: dict[str, Any]) -> dict[str, Any]:
    path = artifact_home.resolve_state_path(cfg)
    if not os.path.isfile(path):
        return {"version": 1, "files": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "files": {}}
    if not isinstance(data.get("files"), dict):
        data["files"] = {}
    return data


def _host_ok(handler: BaseHTTPRequestHandler, port: int) -> bool:
    host = (handler.headers.get("Host") or "").split("@")[-1].strip().lower()
    allowed = {
        f"127.0.0.1:{port}",
        f"localhost:{port}",
        "127.0.0.1",
        "localhost",
        f"[::1]:{port}",
        "[::1]",
    }
    return host in allowed


def _health_lines(cfg: dict[str, Any], state: dict[str, Any]) -> tuple[str, str, str]:
    paused = runtime_pause.is_paused()
    running = "일시정지 (추론만 멈춤)" if paused else "실행 중"
    last_utc = str(state.get("last_inference_utc") or "").strip() or "(아직 없음)"
    backend = str(state.get("last_inference_backend") or "").strip()
    model = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    mock = bool(model.get("use_mock", True)) or backend in ("", "mock")
    mode = "연습 모드 (mock) — 진짜 분석이 아님" if mock else f"모델: {backend or 'unknown'}"
    return running, last_utc, mode


def _sensitive_rows(cfg: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    items: list[tuple[str, dict[str, Any]]] = []
    for path, meta in files.items():
        if not isinstance(meta, dict):
            continue
        sec = str(meta.get("security_level") or "").upper()
        if sec in ("P1", "P2"):
            items.append((path, meta))
    items.sort(key=lambda pm: str(pm[1].get("last_analyzed_utc") or ""), reverse=True)
    for path, meta in items[:20]:
        sec = str(meta.get("security_level") or "").upper()
        rows.append(
            {
                "name": os.path.basename(path),
                "path": path,
                "label": format_security_level(sec, cfg),
                "summary": str(meta.get("summary") or "").strip()[:160],
            }
        )
    return rows


def _page_html(cfg: dict[str, Any], *, flash: str = "", error: str = "") -> str:
    state = _load_state(cfg)
    running, last_utc, mode = _health_lines(cfg, state)
    report_path = artifact_home.resolve_report_path(cfg)
    today_md = status_dashboard.build_status_markdown(cfg, state, report_path)
    # Keep the live page short: health + compose; link snapshot for the rest.
    cands = compose.candidate_rows(cfg, state, limit=36)
    threads = compose.thread_options(state)
    sensitive = _sensitive_rows(cfg, state)
    composed = compose.composed_dir(cfg)
    settings = compose.compose_settings(cfg)
    max_n = settings["max_sources"]

    def esc(s: str) -> str:
        return html.escape(s, quote=True)

    checks = []
    for row in cands:
        fid = esc(row["file_id"])
        label = esc(row["basename"])
        meta = esc(row["security_label"] or row["security_level"])
        extra = []
        if row["draft"] and not row["final"]:
            extra.append("이전 버전")
        if row["final"]:
            extra.append("최종 파일명")
        if row["stale"]:
            extra.append("다시 분류 대기")
        if not row["body_ok"]:
            extra.append("민감 — 본문 없이 목록만")
        hint = f" ({', '.join(extra)})" if extra else ""
        summary = esc((row["summary"] or "")[:80])
        checks.append(
            f'<label class="chk"><input type="checkbox" name="fid" value="{fid}"> '
            f"<code>{label}</code> {meta}{esc(hint)}"
            f"<div class=\"sum\">{summary}</div></label>"
        )
    if not checks:
        checks.append("<p>아직 분류된 파일이 없음. 개를 잠시 돌려 문서를 저장하세요.</p>")

    th_opts = ['<option value="">(파일만 직접 고름)</option>']
    for th in threads:
        th_opts.append(f'<option value="{esc(th["id"])}">{esc(th["title"])}</option>')

    sens_html = ["<p>본문은 보여 주지 않음.</p>"]
    if sensitive:
        sens_html = ["<ul>"]
        for row in sensitive:
            sens_html.append(
                f"<li><strong>{esc(row['name'])}</strong> — {esc(row['label'])}<br>"
                f"<code>{esc(row['path'])}</code><br>{esc(row['summary'])}</li>"
            )
        sens_html.append("</ul>")

    flash_html = f'<p class="ok">{esc(flash)}</p>' if flash else ""
    err_html = f'<p class="err">{esc(error)}</p>' if error else ""
    paused = runtime_pause.is_paused()
    pause_label = "추론 재개" if paused else "추론 일시정지"

    return f"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DocuDog 현황</title>
<style>
body {{ font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; margin: 0;
  background: #f7f4ef; color: #1c1917; line-height: 1.45; }}
main {{ max-width: 920px; margin: 0 auto; padding: 1.5rem 1.2rem 3rem; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ font-size: 1.1rem; margin-top: 1.6rem; }}
.card {{ background: #fffdf9; border: 1px solid #d6d3d1; border-radius: 8px;
  padding: 0.85rem 1rem; }}
.chk {{ display: block; margin: 0.45rem 0; padding: 0.35rem 0; border-bottom: 1px solid #eee; }}
.sum {{ color: #57534e; font-size: 0.9rem; margin-left: 1.4rem; }}
textarea, select, input[type=text] {{ width: 100%; max-width: 40rem; }}
textarea {{ min-height: 4.5rem; }}
button {{ background: #0f766e; color: #fff; border: 0; padding: 0.45rem 0.9rem;
  border-radius: 6px; cursor: pointer; margin-right: 0.4rem; }}
button.secondary {{ background: #57534e; }}
.ok {{ color: #166534; }}
.err {{ color: #b91c1c; }}
code {{ font-size: 0.92em; }}
.muted {{ color: #57534e; }}
</style>
</head><body><main>
<h1>DocuDog 현황</h1>
<p class="muted">이 PC에서만 열림. 채팅 질문은 Cursor/Claude. 폴더를 정리하는 화면이 아님.</p>
{flash_html}{err_html}
<div class="card">
<p><strong>상태:</strong> {esc(running)}</p>
<p><strong>마지막 분류:</strong> {esc(last_utc)}</p>
<p><strong>모드:</strong> {esc(mode)}</p>
<form method="post" action="/pause" style="margin-top:0.5rem">
<button type="submit" class="secondary">{esc(pause_label)}</button>
</form>
</div>
<h2>민감 (제목만)</h2>
{''.join(sens_html)}
<h2>만들기</h2>
<p>이미 분류된 파일만. 최대 {max_n}개. 결과는 <code>{esc(composed)}</code></p>
<form method="post" action="/compose">
<p>스레드로 후보 채우기:
<select name="thread_id">{''.join(th_opts)}</select>
<span class="muted">(선택하면 아래 체크 대신 그 묶음을 씀)</span></p>
<div>{''.join(checks)}</div>
<p>종류
<select name="kind">
<option value="brief">요약·보고서</option>
<option value="handover">인수인계 / OJT</option>
</select></p>
<p>요청 문장<br>
<textarea name="intent" placeholder="임원용 10줄, 일정만 표"></textarea></p>
<p>형식
<select name="formats">
<option value="md,html">Markdown + HTML</option>
<option value="md">Markdown만</option>
<option value="md,html,docx">Markdown + HTML + Word (얇음)</option>
</select></p>
<p><button type="submit">만들기</button></p>
</form>
<h2>스냅샷 설명</h2>
<p class="muted">아래는 디스크에 저장된 status 요약임. 숫자 상세는 데이터 폴더의 DocuDog_status.html.</p>
<pre style="white-space:pre-wrap;font-size:0.85rem">{esc(today_md[:4000])}</pre>
</main></body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("operator http: " + fmt, *args)

    def _cfg(self) -> dict[str, Any]:
        return _cfg

    def _send(self, code: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self) -> bool:
        port = dashboard_settings(self._cfg())["port"]
        if self.client_address and self.client_address[0] not in ("127.0.0.1", "::1"):
            self._send(403, "local only")
            return False
        if not _host_ok(self, port):
            self._send(403, "bad host")
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard():
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, _page_html(self._cfg()))
            return
        if path == "/health":
            state = _load_state(self._cfg())
            running, last_utc, mode = _health_lines(self._cfg(), state)
            payload = {
                "running": running,
                "last_inference_utc": last_utc,
                "mode": mode,
                "paused": runtime_pause.is_paused(),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
            return
        self._send(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard():
            return
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(max(0, min(length, 2_000_000))).decode("utf-8", errors="replace")
        form = parse_qs(raw, keep_blank_values=True)
        cfg = self._cfg()
        if path == "/pause":
            runtime_pause.set_paused(not runtime_pause.is_paused())
            self._send(200, _page_html(cfg, flash="일시정지 상태를 바꿈."))
            return
        if path == "/compose":
            kind = (form.get("kind") or ["brief"])[0]
            intent = (form.get("intent") or [""])[0]
            formats = [x.strip() for x in (form.get("formats") or ["md,html"])[0].split(",") if x.strip()]
            thread_id = (form.get("thread_id") or [""])[0].strip()
            fids = form.get("fid") or []
            state = _load_state(cfg)
            result = compose.compose(
                cfg,
                state,
                kind=kind,
                intent=intent,
                file_ids_selected=fids,
                thread_id=thread_id,
                formats=formats,
                report_path=artifact_home.resolve_report_path(cfg),
            )
            if not result.get("ok"):
                self._send(200, _page_html(cfg, error=str(result.get("error") or "만들기 실패")))
                return
            paths = result.get("paths") or {}
            md = paths.get("md") or ""
            html_path = paths.get("html") or ""
            docx = paths.get("docx") or ""
            bits = [f"저장함: {md}"]
            if html_path:
                bits.append(f"HTML: {html_path}")
            if docx:
                bits.append(f"Word: {docx}")
            flash = " · ".join(bits)
            self._send(200, _page_html(cfg, flash=flash))
            return
        self._send(404, "not found")


def start_operator_http(cfg: dict[str, Any], *, config_dir: str = "") -> str | None:
    """Bind 127.0.0.1 only. Returns base URL or None."""
    global _httpd, _cfg, _config_dir
    ds = dashboard_settings(cfg)
    if not ds["enabled"]:
        return None
    with _httpd_lock:
        if _httpd is not None:
            _cfg = cfg
            return operator_url(cfg)
        _cfg = cfg
        _config_dir = config_dir
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", ds["port"]), _Handler)
        except OSError as e:
            logger.warning("Operator page listen failed on 127.0.0.1:%s: %s", ds["port"], e)
            return None
        _httpd = httpd
        t = threading.Thread(target=httpd.serve_forever, name="docudog-operator-http", daemon=True)
        t.start()
        url = operator_url(cfg)
        logger.info("Operator page at %s (loopback only, not opened automatically)", url)
        return url


def open_operator_page(cfg: dict[str, Any], *, config_dir: str = "") -> str | None:
    """Open in the default browser. Never called at process start."""
    url = start_operator_http(cfg, config_dir=config_dir)
    if url:
        webbrowser.open(url)
        return url
    report_path = artifact_home.resolve_report_path(cfg)
    status_path = status_dashboard.resolve_status_path(cfg, report_path)
    from .reporter import html_path_for_report

    html_path = html_path_for_report(status_path)
    target = html_path if os.path.isfile(html_path) else status_path
    if os.path.isfile(target):
        webbrowser.open(path_to_uri(target))
        return target
    logger.warning("No operator URL and no status file at %s", target)
    return None


def path_to_uri(path: str) -> str:
    return "file:///" + os.path.abspath(path).replace("\\", "/")
