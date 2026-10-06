"""
Reglas de prevención de LC/FT aplicadas a las operaciones de pago de primas.
IMPORTANTE: los umbrales son PARÁMETROS de referencia, no los valores normativos. El Oficial de Cumplimiento
debe configurarlos conforme a la normativa vigente de la SUDEASEG antes de usar los hallazgos.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterator

from app.core.security.crypto import normalize_id
from app.modules.analytics.calculations import D

from ..models import Finding, Severity
from .base import Rule
from .duplicates import _d

_COMMON = {"thresholds": {"USD": "10000"}, "methods": ["CASH"]}


def _eligible(rule: Rule, ctx, skipped: list) -> Iterator[tuple[dict, Decimal]]:
    th = {k.upper(): D(v) for k, v in rule.params["thresholds"].items()}
    methods = {m.upper() for m in rule.params["methods"]} if rule.params.get("methods") else None
    unknown = set()
    for p in ctx.payments():
        if methods and str(p["method"]).upper() not in methods:
            continue
        cur = str(p["currency"]).upper()
        if cur not in th:
            unknown.add(cur)
            continue
        yield p, th[cur]
    for cur in sorted(unknown):
        skipped.append({"grupo": f"pagos en {cur}", "motivo": "sin umbral configurado para esta moneda"})


class CashThresholdRule(Rule):
    code = "LCFT-THRESHOLD"
    title = "Operación individual igual o superior al umbral"
    default_params = dict(_COMMON)

    def __init__(self, params=None):
        super().__init__(params)
        self.skipped: list[dict] = []

    def run(self, ctx) -> Iterator[Finding]:
        self.skipped = []
        for p, limit in _eligible(self, ctx, self.skipped):
            amt = D(p["amount"])
            if amt >= limit:
                yield Finding(self.code, Severity.HIGH, "payment", str(p["payment_id"]), min(100, float(70 + 10 * (amt / limit))),
                              f"Pago de {amt} {p['currency']} por {p['method']} (umbral {limit}).",
                              {"pagador": "[ver registro]", "poliza": p["policy_number"], "monto": str(amt),
                               "moneda": p["currency"], "metodo": p["method"], "fecha": str(p["paid_at"]),
                               "umbral": str(limit)}, {"payment": str(p["payment_id"])})


class StructuringRule(Rule):
    """Fraccionamiento: varios pagos por debajo del umbral cuyo total en la ventana lo alcanza o supera."""
    code = "LCFT-STRUCTURING"
    title = "Posible fraccionamiento de operaciones"
    default_params = {**_COMMON, "window_days": 30, "min_count": 3}

    def __init__(self, params=None):
        super().__init__(params)
        self.skipped: list[dict] = []

    def run(self, ctx) -> Iterator[Finding]:
        self.skipped = []
        groups: dict[tuple, list] = defaultdict(list)
        limits: dict[str, Decimal] = {}
        for p, limit in _eligible(self, ctx, self.skipped):
            if D(p["amount"]) < limit:
                key = (normalize_id(str(p["payer_id"])), str(p["currency"]).upper())
                groups[key].append(p)
                limits[key[1]] = limit
        win, min_n = int(self.params["window_days"]), int(self.params["min_count"])
        for (payer, cur), rows in groups.items():
            rows.sort(key=lambda r: _d(r["paid_at"]))
            i = 0
            while i < len(rows):
                j = i
                while j + 1 < len(rows) and (_d(rows[j + 1]["paid_at"]) - _d(rows[i]["paid_at"])).days <= win:
                    j += 1
                window = rows[i:j + 1]
                total = sum((D(r["amount"]) for r in window), Decimal(0))
                if len(window) >= min_n and total >= limits[cur]:
                    first, last = _d(window[0]["paid_at"]), _d(window[-1]["paid_at"])
                    yield Finding(self.code, Severity.HIGH, "payer", payer, min(100, 70 + len(window) * 3),
                                  f"{len(window)} pagos en {(last - first).days + 1} días suman {total} {cur}, "
                                  f"cada uno por debajo del umbral ({limits[cur]}).",
                                  {"moneda": cur, "cantidad": len(window), "total": str(total), "desde": str(first),
                                   "hasta": str(last), "pagos": [r["payment_id"] for r in window],
                                   "umbral": str(limits[cur])},
                                  {"payer": payer, "moneda": cur, "desde": str(first), "hasta": str(last)})
                    i = j + 1                       # saltar la ventana ya reportada
                else:
                    i += 1


class WatchlistRule(Rule):
    """Asegurado o pagador presente en la lista restrictiva activa (comparación exacta por identificador normalizado)."""
    code = "LCFT-WATCHLIST"
    title = "Coincidencia con lista restrictiva"
    default_params = {}

    def run(self, ctx) -> Iterator[Finding]:
        wl = ctx.watchlist()
        if not wl:
            return
        for p in ctx.policies():
            key = normalize_id(str(p["insured_id"]))
            if key in wl:
                yield Finding(self.code, Severity.CRITICAL, "policy", str(p["policy_number"]), 98,
                              "El asegurado coincide con una lista restrictiva.",
                              {"lista": wl[key], "rol": "ASEGURADO", "poliza": p["policy_number"]},
                              {"rol": "ASEGURADO", "id": key, "poliza": str(p["policy_number"])})
        for p in ctx.payments():
            key = normalize_id(str(p["payer_id"]))
            if key in wl:
                yield Finding(self.code, Severity.CRITICAL, "payment", str(p["payment_id"]), 98,
                              "El pagador coincide con una lista restrictiva.",
                              {"lista": wl[key], "rol": "PAGADOR", "poliza": p["policy_number"],
                               "monto": str(p["amount"]), "moneda": p["currency"]},
                              {"rol": "PAGADOR", "id": key, "payment": str(p["payment_id"])})
