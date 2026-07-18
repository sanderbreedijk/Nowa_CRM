from __future__ import annotations

from nowa_crm.integrations.contracts import IncomingCall

class ColigoAdapter:
    """Lokaal Coligo-invoerpunt zonder opgeslagen cloudwachtwoorden of tokens."""

    def __init__(self) -> None:
        self._running = False

    def start(self, on_call) -> None:
        self._running = True
        self._on_call = on_call

    def stop(self) -> None:
        self._running = False

    def ingest(self, phone_number: str, external_id: str = "", display_name: str = "") -> None:
        if self._running and phone_number.strip():
            self._on_call(IncomingCall(external_id,phone_number.strip(),display_name))

