"""Runtime pause flag for tray (inference only)."""

from __future__ import annotations

import threading

_pause = threading.Event()


def is_paused() -> bool:
    return _pause.is_set()


def set_paused(value: bool) -> None:
    if value:
        _pause.set()
    else:
        _pause.clear()
