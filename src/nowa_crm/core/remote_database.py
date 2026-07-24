from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from cryptography.fernet import Fernet, InvalidToken


def _pack(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [_pack(item) for item in value]
    return value


def _unpack(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__bytes__"}:
        return base64.b64decode(value["__bytes__"])
    return value


class RemoteRow(Mapping):
    def __init__(self, columns: list[str], values: list[Any]):
        self._columns=columns;self._values=[_unpack(value) for value in values]
        self._data=dict(zip(columns,self._values))

    def __getitem__(self, key):
        return self._values[key] if isinstance(key,int) else self._data[key]

    def __iter__(self): return iter(self._columns)
    def __len__(self): return len(self._columns)
    def keys(self): return self._data.keys()


class RemoteCursor:
    def __init__(self, payload: dict):
        columns=payload.get("columns",[])
        self._rows=[RemoteRow(columns,row) for row in payload.get("rows",[])]
        self.lastrowid=payload.get("lastrowid")
        self.rowcount=int(payload.get("rowcount",-1))

    def fetchone(self): return self._rows[0] if self._rows else None
    def fetchall(self): return list(self._rows)
    def __iter__(self): return iter(self._rows)


class RemoteConnection:
    def __init__(self, database: "RemoteDatabase", transaction_id: str):
        self.database=database;self.transaction_id=transaction_id

    def execute(self, sql: str, parameters=()) -> RemoteCursor:
        result=self.database._request("execute",{"transaction_id":self.transaction_id,
            "sql":sql,"parameters":_pack(list(parameters))})
        return RemoteCursor(result)

    def executemany(self, sql: str, parameters) -> RemoteCursor:
        result=self.database._request("executemany",{"transaction_id":self.transaction_id,
            "sql":sql,"parameters":_pack([list(row) for row in parameters])})
        return RemoteCursor(result)


class RemoteDatabase:
    """DB-API-achtige client voor de centrale NOWA-databaseservice."""

    is_remote=True

    def __init__(self, host: str, port: int, access_key: str, tls: bool = True):
        self.base_url=f"http://{host}:{int(port)}/v1"
        self.access_key=access_key
        self.fernet=Fernet(base64.urlsafe_b64encode(hashlib.sha256(access_key.encode()).digest()))
        self.authorization=hashlib.sha256(("nowa:"+access_key).encode()).hexdigest()
        self.path=Path(f"centrale-server-{host}")

    def _request(self, endpoint: str, payload: dict | None = None, timeout: float = 15) -> dict:
        encrypted=self.fernet.encrypt(json.dumps(payload or {}).encode("utf-8"))
        request=urllib.request.Request(f"{self.base_url}/{endpoint}",
            data=encrypted,
            headers={"Content-Type":"application/octet-stream","Authorization":f"NOWA {self.authorization}"},
            method="POST")
        try:
            with urllib.request.urlopen(request,timeout=timeout) as response:
                return json.loads(self.fernet.decrypt(response.read()).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:detail=json.loads(self.fernet.decrypt(exc.read()).decode("utf-8")).get("error",str(exc))
            except Exception:detail=str(exc)
            raise ConnectionError(detail) from exc
        except OSError as exc:
            raise ConnectionError(f"De centrale NOWA CRM-server is niet bereikbaar: {exc}") from exc

    def health(self) -> dict: return self._request("health",timeout=5)
    def vault_key(self) -> bytes:
        return base64.b64decode(self._request("vault-key")["key"])
    def migrate(self) -> None: self.health()

    @contextmanager
    def transaction(self) -> Iterator[RemoteConnection]:
        transaction_id=self._request("begin")["transaction_id"]
        try:
            yield RemoteConnection(self,transaction_id)
        except Exception:
            try:self._request("finish",{"transaction_id":transaction_id,"commit":False})
            finally:raise
        else:
            self._request("finish",{"transaction_id":transaction_id,"commit":True})

    def backup(self, label: str = "handmatig") -> Path:
        from nowa_crm.core.paths import data_dir
        result=self._request("backup",{"label":label},timeout=120)
        folder=data_dir()/"backups";folder.mkdir(parents=True,exist_ok=True)
        target=folder/f"nowa-centraal-{label}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
        target.write_bytes(base64.b64decode(result["database"]))
        return target

    def import_sqlite(self, source: Path) -> dict:
        payload=base64.b64encode(source.read_bytes()).decode("ascii")
        return self._request("import",{"database":payload},timeout=120)

