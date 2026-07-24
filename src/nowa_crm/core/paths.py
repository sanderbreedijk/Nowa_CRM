from __future__ import annotations

import os
import json
from pathlib import Path


def data_dir() -> Path:
    root = os.getenv("NOWA_DATA_DIR")
    path = Path(root) if root else Path(os.getenv("LOCALAPPDATA", Path.home())) / "NOWA" / "CRM"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "nowa.sqlite3"



def content_dir() -> Path:
    """Gedeelde documentopslag zonder database of instellingen op het netwerk."""
    local=data_dir();config=local/"multiuser.json"
    if config.exists():
        try:
            folder=json.loads(config.read_text(encoding="utf-8")).get("shared_documents","").strip()
            if folder:
                path=Path(folder);path.mkdir(parents=True,exist_ok=True);return path
        except (OSError,ValueError,TypeError):
            pass
    return local
