from __future__ import annotations


class ColigoAdapter:
    """Voorbereid koppelvlak; authenticatie en API-URL worden later configureerbaar."""

    def __init__(self) -> None:
        self._running = False

    def start(self, on_call) -> None:
        self._running = True
        self._on_call = on_call

    def stop(self) -> None:
        self._running = False

