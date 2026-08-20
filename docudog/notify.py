"""Optional OS toast for critical (P1) classifications."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def notify_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("notify_settings")
    if isinstance(raw, dict) and "enabled" in raw:
        return bool(raw.get("enabled"))
    return True


def maybe_p1_toast(cfg: dict[str, Any], basename: str) -> None:
    if not notify_enabled(cfg):
        return
    title = "DocuDog"
    msg = f"P1 (대외비) 문서: {basename}"
    try:
        from winotify import Notification

        Notification(app_id="DocuDog", title=title, msg=msg, duration="short").show()
    except Exception:
        logger.info("P1 notice: %s", msg)
