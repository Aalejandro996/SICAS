"""
Cálculos financieros y actuariales básicos con Decimal (nunca float para dinero).

Convenciones (DEBEN validarse con el área actuarial y la normativa vigente de la SUDEASEG):
  - Redondeo monetario: 2 decimales, ROUND_HALF_UP, aplicado SOLO al resultado final (no a pasos intermedios).
  - Vigencia semiabierta [inicio, fin): días totales = (fin - inicio).days.
  - Prima devengada: pro-rata por días exactos. Reserva de prima no devengada = prima - devengada.
  - Los importes de distinta moneda NO se suman: se convierten con una tasa explícita y fechada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable

CENT = Decimal("0.01")


def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))          # evita el ruido binario de float (0.1 -> 0.1000000000000000055)
    try:
        return Decimal(str(x).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Monto inválido: {x!r}") from exc


def money(x) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def sum_exact(values: Iterable) -> Decimal:
    total = Decimal(0)
    for v in values:
        total += D(v)
    return total


def ratio(num, den, places: int = 4) -> Decimal | None:
    """num/den redondeado; None si el denominador es cero (no se inventa un valor)."""
    d = D(den)
    if d == 0:
        return None
    return (D(num) / d).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self):
        object.__setattr__(self, "amount", D(self.amount))
        object.__setattr__(self, "currency", self.currency.upper())

    def __add__(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise ValueError(f"No se pueden sumar {self.currency} y {other.currency} sin tasa de cambio")
        return Money(self.amount + other.amount, self.currency)

    def convert(self, to: str, rate: Decimal) -> "Money":
        """rate = unidades de `to` por 1 unidad de la moneda origen (p. ej. VES por USD)."""
        r = D(rate)
        if r <= 0:
            raise ValueError("La tasa de cambio debe ser positiva")
        return Money(self.amount * r, to)


# ---------------- Primas y reservas ----------------
def _term(start: date, end: date) -> int:
    days = (end - start).days
    if days <= 0:
        raise ValueError("La vigencia debe tener al menos un día")
    return days


def earned_premium(premium, start: date, end: date, as_of: date) -> Decimal:
    total = _term(start, end)
    elapsed = min(max((as_of - start).days, 0), total)
    return money(D(premium) * elapsed / total)


def unearned_premium_reserve(premium, start: date, end: date, as_of: date) -> Decimal:
    """Reserva de prima no devengada (pro-rata). Se calcula sin redondeos intermedios."""
    total = _term(start, end)
    elapsed = min(max((as_of - start).days, 0), total)
    return money(D(premium) * (total - elapsed) / total)


def incurred_claims(paid, reserve_end, reserve_start) -> Decimal:
    """Siniestros incurridos = pagados + reserva final - reserva inicial."""
    return money(D(paid) + D(reserve_end) - D(reserve_start))


# ---------------- Indicadores ----------------
def loss_ratio(incurred, earned_prem) -> Decimal | None:
    return ratio(incurred, earned_prem)


def expense_ratio(expenses, earned_prem) -> Decimal | None:
    return ratio(expenses, earned_prem)


def combined_ratio(incurred, expenses, earned_prem) -> Decimal | None:
    return ratio(D(incurred) + D(expenses), earned_prem)


def variance(actual, expected) -> dict:
    a, e = D(actual), D(expected)
    return {"absoluta": money(a - e), "porcentual": ratio(a - e, e)}


def severity_frequency(total_claims_amount, claim_count, exposed_policies):
    """Severidad media (monto/n.º siniestros) y frecuencia (siniestros/pólizas expuestas)."""
    return {"severidad": None if claim_count == 0 else money(D(total_claims_amount) / claim_count),
            "frecuencia": ratio(claim_count, exposed_policies)}
