from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IncomingCall:
    external_id: str
    phone_number: str
    display_name: str = ""


class TelephonyProvider(Protocol):
    def start(self, on_call) -> None: ...
    def stop(self) -> None: ...


class MailProvider(Protocol):
    def send(self, to: list[str], subject: str, body: str) -> str: ...
    def recent_messages(self, customer_email: str) -> list[dict]: ...

