from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from nowa_crm import __version__

REPOSITORY = "sanderbreedijk/Nowa_CRM"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
FORBIDDEN_NAMES = {"vault.key", ".env"}
FORBIDDEN_SUFFIXES = {".sqlite3", ".db", ".pem", ".pfx"}
ALLOWED_RUNTIME_CERTIFICATES = {"cacert.pem"}
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 10_000


def _version_tuple(value: str) -> tuple[int, ...]:
    clean = value.strip().lower().removeprefix("v").split("-")[0]
    try:
        return tuple(int(part) for part in clean.split("."))
    except ValueError:
        return (0,)


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    name: str
    notes: str
    asset_url: str
    web_url: str

    @property
    def is_newer(self) -> bool:
        return _version_tuple(self.version) > _version_tuple(__version__)


class UpdateService:
    def latest(self) -> ReleaseInfo | None:
        request = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": f"NOWA-CRM/{__version__}"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(
                    "De GitHub-repository is privé. Download het Windows-pakket "
                    "na aanmelding bij GitHub en kies daarna 'Updatepakket kiezen'."
                ) from exc
            raise RuntimeError(f"GitHub gaf fout {exc.code}") from exc
        assets = payload.get("assets") or []
        asset = next((item for item in assets if item.get("name") == "NOWA_CRM-Windows.zip"), None)
        if not asset:
            asset = next((item for item in assets if str(item.get("name", "")).lower().endswith(".zip")), None)
        return ReleaseInfo(
            version=str(payload.get("tag_name") or "0"),
            name=str(payload.get("name") or payload.get("tag_name") or "Release"),
            notes=str(payload.get("body") or ""),
            asset_url=str(asset.get("browser_download_url")) if asset else "",
            web_url=str(payload.get("html_url") or RELEASES_URL),
        )

    def download(self, release: ReleaseInfo) -> Path:
        if not release.asset_url.startswith("https://github.com/"):
            raise RuntimeError("Onveilige of onverwachte downloadlocatie")
        folder = Path(tempfile.mkdtemp(prefix="nowa-update-"))
        archive = folder / "NOWA_CRM-update.zip"
        request = urllib.request.Request(release.asset_url, headers={"User-Agent": f"NOWA-CRM/{__version__}"})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        return self._safe_extract(archive, folder / "pakket")

    def prepare_local_package(self, archive: Path) -> Path:
        archive = archive.resolve()
        if not archive.is_file() or archive.suffix.lower() != ".zip":
            raise RuntimeError("Kies het originele Windows-updatepakket in ZIP-formaat")
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Het gekozen updatepakket is onverwacht groot")
        folder = Path(tempfile.mkdtemp(prefix="nowa-update-"))
        return self._safe_extract(archive, folder / "pakket")

    def _safe_extract(self, archive: Path, destination: Path) -> Path:
        destination.mkdir(parents=True)
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise RuntimeError("Update bevat onverwacht veel bestanden")
            if sum(info.file_size for info in entries) > MAX_EXTRACTED_BYTES:
                raise RuntimeError("De uitgepakte update is onverwacht groot")
            for info in entries:
                path = PurePosixPath(info.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise RuntimeError("Update bevat een ongeldig bestandspad")
                name = path.name.lower()
                trusted_runtime_certificate = (
                    name in ALLOWED_RUNTIME_CERTIFICATES
                    and "_internal" in {part.lower() for part in path.parts}
                    and path.parent.name.lower() == "certifi"
                )
                if (name in FORBIDDEN_NAMES or any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)) and not trusted_runtime_certificate:
                    raise RuntimeError(f"Update bevat verboden gegevensbestand: {path.name}")
            package.extractall(destination)
        candidates = list(destination.rglob("NOWA_CRM.exe"))
        if not candidates:
            raise RuntimeError("Update bevat geen NOWA_CRM.exe")
        return candidates[0].parent

    def install_after_exit(self, package_dir: Path) -> None:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Installeren kan alleen vanuit de gebouwde Windows-app")
        install_dir = Path(sys.executable).resolve().parent
        helper = package_dir.parent / "install-update.ps1"
        script = f"""$ErrorActionPreference='Stop'
$pidToWait={os.getpid()}
$source='{str(package_dir).replace("'", "''")}'
$target='{str(install_dir).replace("'", "''")}'
Wait-Process -Id $pidToWait -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse -Force
Start-Process -FilePath (Join-Path $target 'NOWA_CRM.exe')
Remove-Item -LiteralPath $PSCommandPath -Force
"""
        helper.write_text(script, encoding="utf-8-sig")
        subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)], creationflags=subprocess.CREATE_NO_WINDOW)
