"""Default artifact home: %USERPROFILE%/.docudog (not the watch folder)."""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

from .paths_util import normalize_fs_path

logger = logging.getLogger(__name__)


def artifact_home(cfg: dict[str, Any] | None = None) -> str:
    raw = ""
    if isinstance(cfg, dict):
        paths = cfg.get("paths") or {}
        if isinstance(paths, dict):
            raw = str(paths.get("artifact_home") or "").strip()
    if raw:
        return normalize_fs_path(os.path.expandvars(raw))
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.path.expanduser("~")
    return normalize_fs_path(os.path.join(home, ".docudog"))


def default_state_path(cfg: dict[str, Any] | None = None) -> str:
    return os.path.join(artifact_home(cfg), "DocuDog_state.json")


def default_report_path(cfg: dict[str, Any] | None = None) -> str:
    return os.path.join(artifact_home(cfg), "classification_report.md")


def resolve_state_path(cfg: dict[str, Any]) -> str:
    paths = cfg.get("paths") if isinstance(cfg.get("paths"), dict) else {}
    raw = str((paths or {}).get("state_path") or "").strip()
    if raw:
        return normalize_fs_path(os.path.expandvars(raw))
    return default_state_path(cfg)


def resolve_report_path(cfg: dict[str, Any]) -> str:
    paths = cfg.get("paths") if isinstance(cfg.get("paths"), dict) else {}
    raw = str((paths or {}).get("report_path") or "").strip()
    if raw:
        return normalize_fs_path(os.path.expandvars(raw))
    return default_report_path(cfg)


def _hide_windows_dir(path: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        logger.debug("Could not set hidden attribute on %s", path, exc_info=True)


def _legacy_bundle_dir() -> str:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, "Documents", "DocuDog")


def maybe_migrate_legacy(cfg: dict[str, Any], state_path: str) -> None:
    """
    If the configured state file is missing, copy from the old Documents/DocuDog
    (or loose Documents/*.json) tree. Never deletes the source.
    """
    if os.path.isfile(state_path):
        return
    dest_dir = os.path.dirname(state_path)
    if not dest_dir:
        return
    legacy_dir = _legacy_bundle_dir()
    legacy_state = os.path.join(legacy_dir, "DocuDog_state.json")
    copied = False
    try:
        if os.path.isdir(legacy_dir) and os.path.isfile(legacy_state):
            os.makedirs(dest_dir, exist_ok=True)
            for name in os.listdir(legacy_dir):
                src = os.path.join(legacy_dir, name)
                dst = os.path.join(dest_dir, name)
                if os.path.isfile(src) and not os.path.isfile(dst):
                    shutil.copy2(src, dst)
                    copied = True
            logger.info("Copied legacy DocuDog artifacts from %s -> %s", legacy_dir, dest_dir)
        else:
            loose_state = os.path.join(
                os.environ.get("USERPROFILE") or os.path.expanduser("~"),
                "Documents",
                "DocuDog_state.json",
            )
            if os.path.isfile(loose_state):
                os.makedirs(dest_dir, exist_ok=True)
                dst = os.path.join(dest_dir, "DocuDog_state.json")
                if not os.path.isfile(dst):
                    shutil.copy2(loose_state, dst)
                    copied = True
                loose_report = os.path.join(
                    os.path.dirname(loose_state), "classification_report.md"
                )
                if os.path.isfile(loose_report):
                    rdst = os.path.join(dest_dir, "classification_report.md")
                    if not os.path.isfile(rdst):
                        shutil.copy2(loose_report, rdst)
                logger.info("Copied loose Documents state into %s", dest_dir)
    except OSError as e:
        logger.warning("Legacy artifact copy skipped: %s", e)
        return
    if copied:
        _hide_windows_dir(dest_dir)


def ensure_artifact_home(cfg: dict[str, Any], state_path: str) -> None:
    dest = os.path.dirname(os.path.abspath(state_path))
    if dest:
        os.makedirs(dest, exist_ok=True)
        if os.path.normcase(dest) == os.path.normcase(artifact_home(cfg)):
            _hide_windows_dir(dest)
    maybe_migrate_legacy(cfg, state_path)
