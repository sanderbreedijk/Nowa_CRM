from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nowa_crm import __version__
from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir


@dataclass(frozen=True)
class BackupInfo:
    folder: Path
    created_at: str
    files: int
    size_bytes: int
    valid: bool


class BackupService:
    """Creates a self-contained, local recovery set without cloud transfer."""

    DATA_FOLDERS = ("documents", "mail-bijlagen")

    def __init__(self, db: Database, root: Path | None = None):
        self.db = db
        self.root = root or data_dir()
        self.backup_root = self.root / "backups" / "herstelsets"

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    def create(self) -> BackupInfo:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        folder = self.backup_root / f"NOWA-herstelset-{stamp}"
        folder.mkdir(parents=True)
        database = self.db.backup("herstelset")
        shutil.move(str(database), folder / "nowa.sqlite3")

        vault_key = self.root / "vault.key"
        if vault_key.exists():
            shutil.copy2(vault_key, folder / "vault.key")
        for name in self.DATA_FOLDERS:
            source = self.root / name
            if source.exists():
                shutil.copytree(source, folder / name)

        files = [path for path in folder.rglob("*") if path.is_file()]
        manifest = {
            "product": "NOWA CRM",
            "version": __version__,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "contains_vault_key": (folder / "vault.key").exists(),
            "files": [
                {
                    "path": path.relative_to(folder).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": self._hash(path),
                }
                for path in files
            ],
        }
        (folder / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.inspect(folder)

    def inspect(self, folder: Path) -> BackupInfo:
        manifest_path = folder / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = manifest["files"]
            valid = bool(entries) and all(
                (folder / entry["path"]).is_file()
                and (folder / entry["path"]).stat().st_size == entry["size"]
                and self._hash(folder / entry["path"]) == entry["sha256"]
                for entry in entries
            )
            return BackupInfo(
                folder=folder,
                created_at=str(manifest.get("created_at", "")),
                files=len(entries),
                size_bytes=sum(int(entry["size"]) for entry in entries),
                valid=valid,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return BackupInfo(folder, "", 0, 0, False)

    def latest(self) -> BackupInfo | None:
        if not self.backup_root.exists():
            return None
        folders = sorted(
            (path for path in self.backup_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        return self.inspect(folders[0]) if folders else None

    def prepare_restore(self, folder: Path) -> BackupInfo:
        folder = folder.resolve()
        info = self.inspect(folder)
        if not info.valid:
            raise RuntimeError("De gekozen herstelset is beschadigd of onvolledig")
        if not (folder / "nowa.sqlite3").is_file():
            raise RuntimeError("De herstelset bevat geen NOWA CRM-database")
        if not (folder / "vault.key").is_file():
            raise RuntimeError("De herstelset bevat geen kluissleutel")
        return info

    def restore_after_exit(self, folder: Path) -> BackupInfo:
        info = self.prepare_restore(folder)
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Herstellen kan alleen vanuit de gebouwde Windows-app")

        # Preserve the current state before any file is replaced.
        self.create()
        executable = Path(sys.executable).resolve()
        helper = Path(tempfile.mkdtemp(prefix="nowa-herstel-")) / "herstel-nowacrm.ps1"
        source = str(info.folder).replace("'", "''")
        target = str(self.root.resolve()).replace("'", "''")
        exe = str(executable).replace("'", "''")
        script = f"""$ErrorActionPreference='Stop'
$pidToWait={os.getpid()}
$source='{source}'
$target='{target}'
$exe='{exe}'
Wait-Process -Id $pidToWait -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
Copy-Item -LiteralPath (Join-Path $source 'nowa.sqlite3') -Destination (Join-Path $target 'nowa.sqlite3') -Force
Copy-Item -LiteralPath (Join-Path $source 'vault.key') -Destination (Join-Path $target 'vault.key') -Force
foreach ($folderName in @('documents','mail-bijlagen')) {{
    $sourceFolder=Join-Path $source $folderName
    $targetFolder=Join-Path $target $folderName
    if (Test-Path -LiteralPath $sourceFolder) {{
        if (Test-Path -LiteralPath $targetFolder) {{ Remove-Item -LiteralPath $targetFolder -Recurse -Force }}
        Copy-Item -LiteralPath $sourceFolder -Destination $targetFolder -Recurse -Force
    }}
}}
Start-Process -FilePath $exe
Remove-Item -LiteralPath $PSCommandPath -Force
"""
        helper.write_text(script, encoding="utf-8-sig")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return info
