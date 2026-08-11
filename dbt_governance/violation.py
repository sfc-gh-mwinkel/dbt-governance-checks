"""A single governance violation."""

from __future__ import annotations

from dataclasses import dataclass

from .config import ERROR, WARNING


@dataclass(frozen=True)
class Violation:
    rule_id: str
    severity: str
    message: str
    model: str
    file_path: str
    column: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity == ERROR

    @property
    def is_warning(self) -> bool:
        return self.severity == WARNING

    def describe(self) -> str:
        target = f"{self.model}.{self.column}" if self.column else self.model
        return f"[{self.rule_id}] {target}: {self.message}"
