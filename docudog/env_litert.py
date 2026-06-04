"""
LiteRT / TFLite 네이티브 stderr(I0000, engine dumps) 억제용 환경 변수.

Python logging과 무관 — 반드시 litert_lm / lib 로드 **전**에 호출할 것.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator

_applied = False


def apply_litert_env_defaults() -> None:
    """Idempotent. Called from main / inference before first Engine()."""
    global _applied
    if _applied:
        return
    # TF / XNNPACK / 많은 TFLite 빌드
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    # 일부 glog 기반 컴포넌트
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("GOOGLE_LOG_LEVEL", "2")
    os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
    _applied = True


@contextlib.contextmanager
def silence_litert_native_stderr() -> Iterator[None]:
    """
    LiteRT / absl / TFLite가 **Python logging이 아닌 fd 2**로 쓰는 덤프를 막기 위해
    stderr(fd 2)를 NUL/``/dev/null``로 잠깐 돌려 놓는 **실험적** 옵션.

    **기본은 끔( stderr 유지 )**. 전역 ``dup2`` 로 fd 2를 바꾸면 Windows 에서
    LiteRT-LM 초기화·``send_message`` 가 멈추거나 프로세스가 끊기는 사례가 있어,
    안정 동작이 우선이다. 억제는 ``TF_CPP_MIN_LOG_LEVEL`` / ``GLOG_minloglevel`` 등
    (``apply_litert_env_defaults``) 로 먼저 줄인다.

    네이티브 stderr 완전 숨김(위험): ``DOCUDOG_SILENCE_LITERT_STDERR=1`` (또는 true/yes)
    """
    val = os.environ.get("DOCUDOG_SILENCE_LITERT_STDERR", "0").strip().lower()
    if val not in ("1", "true", "yes"):
        yield
        return
    devnull: int | None = None
    saved: int | None = None
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved = os.dup(2)
        os.dup2(devnull, 2)
    except OSError:
        if devnull is not None:
            try:
                os.close(devnull)
            except OSError:
                pass
        yield
        return
    try:
        yield
    finally:
        try:
            if saved is not None:
                os.dup2(saved, 2)
                os.close(saved)
            if devnull is not None:
                os.close(devnull)
        except OSError:
            pass
