from __future__ import annotations

import abc
from typing import Any, Iterator

from ..context import DataContext
from ..models import Finding


class Rule(abc.ABC):
    code: str = ""
    title: str = ""
    description: str = ""
    default_params: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None):
        merged = dict(self.default_params)
        merged.update(params or {})
        self.params = merged

    @abc.abstractmethod
    def run(self, ctx: DataContext) -> Iterator[Finding]:
        """Genera hallazgos. Debe ser determinista y de solo lectura."""
