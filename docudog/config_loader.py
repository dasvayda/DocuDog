"""Load config.json and optional overlay (config.yml / config.yaml)."""

from __future__ import annotations

import json
import os
from typing import Any


def expand_vars_recursive(obj: Any) -> Any:
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    if isinstance(obj, list):
        return [expand_vars_recursive(x) for x in obj]
    if isinstance(obj, dict):
        return {k: expand_vars_recursive(v) for k, v in obj.items()}
    return obj


def deep_merge(base: Any, overlay: Any) -> Any:
    """Recursive dict merge; overlay wins. Non-dict values replace."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_dotenv_file(path: str, *, override: bool = False) -> None:
    """
    Minimal .env loader (no python-dotenv dependency).
    Lines: KEY=VALUE, optional quotes, # comments. Does not override existing
    process env unless override=True.
    """
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def resolve_http_api_key(lm_cfg: dict[str, Any] | None) -> str:
    """
    HTTP chat/completions Bearer token.
    Prefer model.lm_studio.api_key; else OPENAI_API_KEY / DOCUDOG_API_KEY from env (.env).
    """
    cfg = lm_cfg if isinstance(lm_cfg, dict) else {}
    raw = str(cfg.get("api_key") or "").strip()
    if raw:
        expanded = os.path.expandvars(raw).strip()
        if expanded and not (
            expanded.startswith("%") and expanded.endswith("%")
        ):
            return expanded
    for name in ("OPENAI_API_KEY", "DOCUDOG_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""


def load_app_config(base_dir: str) -> dict[str, Any]:
    """
    Read config.json, then merge config.yml or config.yaml if present (YAML wins on overlap).
    Loads ``.env`` from base_dir first (secrets; gitignored).
    """
    load_dotenv_file(os.path.join(base_dir, ".env"))

    json_path = os.path.join(base_dir, "config.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(json_path)

    try:
        with open(json_path, encoding="utf-8") as f:
            cfg: dict[str, Any] = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON in {json_path}: line {e.lineno}, column {e.colno}: {e.msg}. "
            "Check for // or /* */ comments, trailing commas, or single-quoted keys."
        ) from e
    cfg = expand_vars_recursive(cfg)

    for name in ("config.yml", "config.yaml"):
        ypath = os.path.join(base_dir, name)
        if not os.path.isfile(ypath):
            continue
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                f"Install PyYAML to use {name}: pip install pyyaml"
            ) from e
        with open(ypath, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if isinstance(loaded, dict):
            cfg = deep_merge(cfg, expand_vars_recursive(loaded))
        break

    return cfg
