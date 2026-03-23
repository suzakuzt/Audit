"""Utilities for creating run directories and writing output files."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def create_run_output_dir(base_dir: Path) -> Path:
    """Create a unique timestamped output directory under ``base_dir``."""
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    run_dir = base_dir / timestamp
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = base_dir / f"{timestamp}_{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_bytes(path: Path, content: bytes) -> None:
    """Write bytes to disk and create parent directories when needed."""
    _ensure_parent(path)
    path.write_bytes(content)


def save_text(path: Path, content: str) -> None:
    """Write UTF-8 text to disk and create parent directories when needed."""
    _ensure_parent(path)
    path.write_text(content, encoding="utf-8")


def save_json(path: Path, payload: Any) -> None:
    """Serialize ``payload`` as pretty JSON and write it as UTF-8 text."""
    _ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
