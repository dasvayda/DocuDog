"""Well-known watch folder presets (Desktop / Downloads / Documents) plus extra UNC roots."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from . import paths_util

logger = logging.getLogger(__name__)

PRESET_IDS: tuple[str, ...] = ("desktop", "downloads", "documents")

_FOLDER_IDS: dict[str, str] = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADA4-286D32C102B9}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
}

_FALLBACK_NAMES: dict[str, str] = {
    "desktop": "Desktop",
    "documents": "Documents",
    "downloads": "Downloads",
}


def _windows_known_folder(folder_id: str) -> str:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    u = uuid.UUID(folder_id)
    guid = GUID(
        u.fields[0],
        u.fields[1],
        u.fields[2],
        (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]),
    )
    SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
    SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    path_ptr = ctypes.c_wchar_p()
    result = SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr))
    if result != 0 or not path_ptr.value:
        raise OSError(result)
    value = path_ptr.value
    ctypes.windll.ole32.CoTaskMemFree(path_ptr)
    return value


def preset_path(preset_id: str) -> str:
    """Absolute path for a well-known user folder. Does not create the folder."""
    key = preset_id.strip().lower()
    home = os.path.expanduser("~")
    fallback = os.path.join(home, _FALLBACK_NAMES.get(key, key))
    folder_id = _FOLDER_IDS.get(key)
    if os.name == "nt" and folder_id:
        try:
            return paths_util.normalize_fs_path(_windows_known_folder(folder_id))
        except OSError:
            logger.debug("Known folder lookup failed for %s; using %s", key, fallback)
    return paths_util.normalize_fs_path(fallback)


def folder_presets(config: dict[str, Any]) -> dict[str, Any]:
    watch = config.get("watch_settings") or {}
    raw = watch.get("folder_presets")
    return raw if isinstance(raw, dict) else {}


def preset_enabled(config: dict[str, Any], preset_id: str) -> bool:
    presets = folder_presets(config)
    if not presets:
        return False
    return bool(presets.get(preset_id))


def extra_directories(config: dict[str, Any]) -> list[str]:
    presets = folder_presets(config)
    raw = presets.get("extra_directories") if presets else None
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def resolve_watch_roots(config: dict[str, Any]) -> list[str]:
    """Union of folder presets, extra_directories, and target_directories (deduped)."""
    watch = config.get("watch_settings") or {}
    raw_dirs = watch.get("target_directories") or []
    paths: list[str] = []
    for preset_id in PRESET_IDS:
        if preset_enabled(config, preset_id):
            paths.append(preset_path(preset_id))
    for item in extra_directories(config):
        paths.append(str(item))
    if isinstance(raw_dirs, list):
        for item in raw_dirs:
            text = str(item).strip()
            if text:
                paths.append(text)
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        try:
            expanded = paths_util.normalize_fs_path(os.path.expandvars(str(raw)))
        except OSError:
            continue
        key = os.path.normcase(expanded)
        if key in seen:
            continue
        seen.add(key)
        out.append(expanded)
        if paths_util.is_unc_path(expanded):
            logger.info(
                "UNC/NAS watch root configured: %s "
                "(single state/report; concurrent writers may hit sharing locks — retries apply)",
                expanded,
            )
    return out


def path_is_under_downloads(config: dict[str, Any], path: str) -> bool:
    try:
        downloads = preset_path("downloads")
        needle = os.path.normcase(downloads)
        hay = os.path.normcase(paths_util.normalize_fs_path(path))
    except OSError:
        return False
    return hay == needle or hay.startswith(needle + os.sep)


def persist_folder_preset(config_dir: str, preset_id: str, enabled: bool) -> dict[str, Any]:
    """Update config.json folder_presets.<id>. Returns the written presets dict."""
    key = preset_id.strip().lower()
    if key not in PRESET_IDS:
        raise ValueError(f"unknown folder preset: {preset_id}")
    json_path = os.path.join(config_dir, "config.json")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid config.json: {json_path}")
    watch = data.setdefault("watch_settings", {})
    if not isinstance(watch, dict):
        watch = {}
        data["watch_settings"] = watch
    presets = watch.setdefault("folder_presets", {})
    if not isinstance(presets, dict):
        presets = {}
        watch["folder_presets"] = presets
    presets[key] = bool(enabled)
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, json_path)
    logger.info(
        "Watch preset %s=%s written to config.json (restart DocuDog to apply folders)",
        key,
        enabled,
    )
    return presets
