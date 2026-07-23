from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer


class ColigoBridge(QObject):
    """Kleine lokale HTTP-ontvanger voor Coligo/telefonie-events."""

    event_received = Signal(dict)
    state_changed = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept)
        self.secret = ""

    @property
    def running(self) -> bool:
        return self.server.isListening()

    def start(self, port: int, secret: str = "") -> bool:
        self.stop()
        self.secret = secret.strip()
        ok = self.server.listen(QHostAddress.SpecialAddress.LocalHost, int(port))
        detail = f"http://127.0.0.1:{port}/coligo" if ok else self.server.errorString()
        self.state_changed.emit(ok, detail)
        return ok

    def stop(self) -> None:
        if self.server.isListening():
            self.server.close()
            self.state_changed.emit(False, "Lokale ontvanger gestopt")

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))

    def _read(self, socket) -> None:
        raw = bytes(socket.readAll())
        if b"\r\n\r\n" not in raw:
            return
        header_blob, body = raw.split(b"\r\n\r\n", 1)
        lines = header_blob.decode("utf-8", "replace").splitlines()
        first = lines[0].split()
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        expected = int(headers.get("content-length", len(body)) or 0)
        if len(body) < expected:
            return
        authorized = not self.secret or headers.get("x-nowa-key", "") == self.secret
        valid_route = len(first) >= 2 and first[0] == "POST" and first[1].split("?", 1)[0] == "/coligo"
        try:
            payload = json.loads(body[:expected].decode("utf-8")) if authorized and valid_route else None
            if not isinstance(payload, dict):
                raise ValueError
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._respond(socket, 401 if not authorized else 400, {"ok": False})
            return
        self.event_received.emit(payload)
        self._respond(socket, 202, {"ok": True, "message": "Event lokaal ontvangen"})

    @staticmethod
    def _respond(socket, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        reason = {202: "Accepted", 400: "Bad Request", 401: "Unauthorized"}.get(status, "OK")
        response = (f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("ascii") + body
        socket.write(response)
        socket.disconnectFromHost()
