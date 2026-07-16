from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Module(Protocol):
    id: str
    title: str

    def start(self) -> None: ...


@dataclass
class ModuleRegistry:
    modules: dict[str, Module]

    def __init__(self) -> None:
        self.modules = {}

    def register(self, module: Module) -> None:
        if module.id in self.modules:
            raise ValueError(f"Module bestaat al: {module.id}")
        self.modules[module.id] = module

    def start_all(self) -> None:
        for module in self.modules.values():
            module.start()

