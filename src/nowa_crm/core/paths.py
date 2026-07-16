from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    root = os.getenv("NOWA_DATA_DIR")
    path = Path(root) if root else Path(os.getenv("LOCALAPPDATA", Path.home())) / "NOWA" / "CRM"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "nowa.sqlite3"

