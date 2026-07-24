from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet


class LocalSecretStore:
    """Versleutelt verbindingsgeheimen lokaal; op Windows gebonden aan de gebruiker."""

    def __init__(self, root: Path):
        self.root = root
        self.key_path = root / ".local-secrets.key"

    def protect(self, value: str) -> str:
        if not value:
            return ""
        if os.name == "nt":
            return "dpapi:" + base64.urlsafe_b64encode(self._dpapi(value.encode(), False)).decode()
        return "fernet:" + Fernet(self._key()).encrypt(value.encode()).decode()

    def unprotect(self, value: str) -> str:
        if not value:
            return ""
        if value.startswith("dpapi:") and os.name == "nt":
            raw = base64.urlsafe_b64decode(value[6:].encode())
            return self._dpapi(raw, True).decode()
        if value.startswith("fernet:"):
            return Fernet(self._key()).decrypt(value[8:].encode()).decode()
        return ""

    def _key(self) -> bytes:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
        return self.key_path.read_bytes()

    @staticmethod
    def _dpapi(data: bytes, decrypt: bool) -> bytes:
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        source_buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        target = Blob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        if decrypt:
            ok = function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
        else:
            ok = function(ctypes.byref(source), "NOWA CRM", None, None, None, 0, ctypes.byref(target))
        if not ok:
            raise OSError("Het lokale verbindingsgeheim kon niet worden verwerkt.")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            kernel32.LocalFree(target.pbData)
