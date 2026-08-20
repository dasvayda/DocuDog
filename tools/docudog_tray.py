#!/usr/bin/env python3
"""Start DocuDog watcher with a system tray (optional). Does not open status.md."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)
sys.argv = [os.path.join(ROOT, "main.py"), "--tray", *sys.argv[1:]]

from main import main  # noqa: E402

if __name__ == "__main__":
    main()
