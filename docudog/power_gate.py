"""Power / battery gate before LLM inference (Windows laptop friendly)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _settings(cfg: dict[str, Any]) -> dict[str, Any]:
    idle = cfg.get("idle_settings") if isinstance(cfg.get("idle_settings"), dict) else {}
    return {
        "min_battery_percent": idle.get("min_battery_percent"),
        "require_charging": bool(idle.get("require_charging", False)),
        "defer_on_thermal_throttle": bool(idle.get("defer_on_thermal_throttle", False)),
    }


def inference_power_allowed(cfg: dict[str, Any]) -> tuple[bool, str]:
    """
    Return (allowed, reason). reason empty when allowed.
    Uses psutil.sensors_battery when available; if no battery (desktop), allow.
    """
    s = _settings(cfg)
    min_pct = s["min_battery_percent"]
    require_charging = s["require_charging"]
    if min_pct is None and not require_charging and not s["defer_on_thermal_throttle"]:
        return True, ""

    try:
        import psutil
    except ImportError:
        return True, ""

    bat = None
    try:
        bat = psutil.sensors_battery()
    except Exception:
        bat = None
    if bat is None:
        # AC-only desktop
        return True, ""

    pct = float(bat.percent) if bat.percent is not None else 100.0
    plugged = bool(bat.power_plugged)

    if require_charging and not plugged:
        return False, f"require_charging (battery={pct:.0f}% unplugged)"
    if min_pct is not None:
        try:
            need = float(min_pct)
        except (TypeError, ValueError):
            need = 0.0
        if pct < need and not plugged:
            return False, f"min_battery_percent={need:g} (now {pct:.0f}% unplugged)"

    if s["defer_on_thermal_throttle"]:
        # Best-effort: Windows has no portable psutil thermal API; skip unless exposed.
        try:
            temps = getattr(psutil, "sensors_temperatures", lambda: {})()
            if isinstance(temps, dict):
                for _name, entries in temps.items():
                    for e in entries or []:
                        cur = getattr(e, "current", None)
                        high = getattr(e, "high", None) or getattr(e, "critical", None)
                        if cur is not None and high is not None and float(cur) >= float(high):
                            return False, f"thermal_throttle ({cur}C >= {high}C)"
        except Exception:
            pass

    return True, ""
