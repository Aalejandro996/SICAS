"""Totales de control y conciliación: lo leído del archivo debe coincidir EXACTAMENTE con lo cargado."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

from app.modules.analytics.calculations import D

MOD = 2 ** 256


@dataclass
class ControlTotals:
    count: int = 0
    amounts: dict[str, Decimal] = field(default_factory=dict)      # por moneda
    hash_sum: int = 0                                               # suma mod 2^256: no depende del orden

    def add(self, row: dict, amount_field: str, currency_field: str = "currency") -> None:
        self.count += 1
        cur = str(row.get(currency_field, "")).upper()
        self.amounts[cur] = self.amounts.get(cur, Decimal(0)) + D(row[amount_field])
        digest = hashlib.sha256("|".join(f"{k}={row[k]}" for k in sorted(row)).encode()).digest()
        self.hash_sum = (self.hash_sum + int.from_bytes(digest, "big")) % MOD

    @property
    def hash_hex(self) -> str:
        return f"{self.hash_sum:064x}"


def reconcile(expected: ControlTotals, loaded_count: int, loaded_amounts: dict[str, Decimal]) -> list[str]:
    """Lista de diferencias (vacía = conciliado). Tolerancia cero: se trabaja con Decimal exacto."""
    diffs = []
    if expected.count != loaded_count:
        diffs.append(f"Registros: esperado {expected.count}, cargado {loaded_count}")
    for cur in sorted(set(expected.amounts) | set(loaded_amounts)):
        e, l = expected.amounts.get(cur, Decimal(0)), D(loaded_amounts.get(cur, 0))
        if e != l:
            diffs.append(f"Monto {cur}: esperado {e}, cargado {l} (diferencia {l - e})")
    return diffs
