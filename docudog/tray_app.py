"""System tray: MCP write, open .docudog, pause inference. No status.md auto-open."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from typing import Any

logger = logging.getLogger(__name__)


def _open_dir(path: str) -> None:
    if not path:
        return
    os.makedirs(path, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        logger.warning("Could not open folder %s: %s", path, e)


def install_startup_shortcut(*, repo_root: str) -> str:
    """Write a Windows Startup .lnk for ``python main.py --tray``. Does not start the watcher."""
    if os.name != "nt":
        raise RuntimeError("Startup shortcut is Windows-only")
    appdata = os.environ.get("APPDATA") or ""
    startup = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")
    os.makedirs(startup, exist_ok=True)
    lnk = os.path.join(startup, "DocuDog.lnk")
    py = os.path.normpath(sys.executable)
    pythonw = os.path.join(os.path.dirname(py), "pythonw.exe")
    target = pythonw if os.path.isfile(pythonw) else py
    main_py = os.path.normpath(os.path.join(repo_root, "main.py"))
    args = f'"{main_py}" --tray'
    script = (
        "$s = New-Object -ComObject WScript.Shell\n"
        f"$sc = $s.CreateShortcut({json.dumps(lnk)})\n"
        f"$sc.TargetPath = {json.dumps(target)}\n"
        f"$sc.Arguments = {json.dumps(args)}\n"
        f"$sc.WorkingDirectory = {json.dumps(os.path.normpath(repo_root))}\n"
        "$sc.WindowStyle = 7\n"
        "$sc.Save()\n"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )
    logger.info("Startup shortcut: %s", lnk)
    return lnk


def attach_tray(cfg: dict[str, Any], *, config_dir: str) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Tray needs pystray and pillow: pip install pystray pillow")
        return

    from . import artifact_home, runtime_pause

    def _icon_image() -> Image.Image:
        img = Image.new("RGB", (64, 64), (15, 118, 110))
        d = ImageDraw.Draw(img)
        d.ellipse((12, 12, 52, 52), fill=(252, 250, 245))
        return img

    def on_mcp(_icon: Any, _item: Any) -> None:
        try:
            import importlib.util

            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script = os.path.join(root, "tools", "docudog_mcp.py")
            spec = importlib.util.spec_from_file_location("docudog_mcp_cli", script)
            if spec is None or spec.loader is None:
                raise RuntimeError("cannot load tools/docudog_mcp.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.write_cursor_mcp(config_dir)
            mod.write_claude_desktop_mcp(config_dir)
            logger.info("MCP configs written (Cursor + Claude Desktop)")
        except Exception:
            logger.exception("MCP write from tray failed")

    def on_open(_icon: Any, _item: Any) -> None:
        _open_dir(artifact_home.artifact_home(cfg))

    def on_pause(_icon: Any, item: Any) -> None:
        runtime_pause.set_paused(not runtime_pause.is_paused())
        logger.info("Inference paused=%s", runtime_pause.is_paused())

    def on_startup(_icon: Any, _item: Any) -> None:
        try:
            install_startup_shortcut(repo_root=config_dir)
        except Exception:
            logger.exception("Startup shortcut failed")

    def on_quit(icon: Any, _item: Any) -> None:
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Write MCP configs", on_mcp),
        pystray.MenuItem("Open data folder", on_open),
        pystray.MenuItem("Install Startup shortcut", on_startup),
        pystray.MenuItem(
            "Pause inference",
            on_pause,
            checked=lambda _: runtime_pause.is_paused(),
        ),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("DocuDog", _icon_image(), "DocuDog", menu)
    if hasattr(icon, "run_detached"):
        icon.run_detached()
    else:
        threading.Thread(target=icon.run, daemon=True).start()
    logger.info("Tray attached (no status.md auto-open)")
