from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterator

from ..models import Finding, Severity
from app.modules.analytics.calculations import D

from .base import Rule


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


class DuplicateClaimsRule(Rule):
    """
    DUP-CLAIM: (1) número de siniestro repetido -> duplicado exacto;
               (2) misma póliza + fecha de ocurrencia + cobertura + monto (redondeado) con distinto número
                   -> posible doble reclamo.
    """
    code = "DUP-CLAIM"
    title = "Siniestros duplicados"
    default_params = {"amount_round": 2, "window_days": 0}

    def run(self, ctx) -> Iterator[Finding]:
        by_number: dict[str, list[dict]] = defaultdict(list)
        by_signature: dict[tuple, list[dict]] = defaultdict(list)
        nd = int(self.params["amount_round"])
        for c in ctx.claims():
            by_number[str(c["claim_number"]).strip().upper()].append(c)
            sig = (c["policy_number"], _d(c["occurrence_date"]), c.get("coverage"),
                   D(c["claimed_amount"]).quantize(Decimal(1).scaleb(-nd)), c.get("currency"))
            by_signature[sig].append(c)

        for number, rows in by_number.items():
            if len(rows) > 1:
                yield Finding(self.code, Severity.HIGH, "claim", number, 80,
                              f"Número de siniestro repetido {len(rows)} veces.",
                              {"tipo": "EXACTO", "ocurrencias": len(rows),
                               "montos": [float(r["claimed_amount"]) for r in rows]},
                              {"tipo": "EXACTO", "n": len(rows)})
        for sig, rows in by_signature.items():
            numbers = sorted({str(r["claim_number"]).strip().upper() for r in rows})
            if len(numbers) > 1:                      # mismo hecho, distintos números
                yield Finding(self.code, Severity.HIGH, "claim", numbers[0], 85,
                              "Posible doble reclamo: misma póliza, fecha, cobertura y monto con distinto número.",
                              {"tipo": "PROBABLE", "poliza": sig[0], "fecha": str(sig[1]), "cobertura": sig[2],
                               "monto": str(sig[3]), "moneda": sig[4], "siniestros": numbers},
                              {"tipo": "PROBABLE", "siniestros": numbers})


class OverlappingPoliciesRule(Rule):
    """
    DUP-POLICY: (1) número de póliza repetido; (2) mismo asegurado + mismo riesgo + mismo ramo
                con vigencias solapadas (doble aseguramiento / fraude de vigencia).
    """
    code = "DUP-POLICY"
    title = "Pólizas duplicadas o con vigencia solapada"
    default_params = {}

    def run(self, ctx) -> Iterator[Finding]:
        seen: dict[str, int] = defaultdict(int)
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for p in ctx.policies():
            seen[str(p["policy_number"]).strip().upper()] += 1
            if p.get("risk_id"):
                groups[(p["insured_id"], p["risk_id"], p["branch"])].append(p)

        for number, n in seen.items():
            if n > 1:
                yield Finding(self.code, Severity.HIGH, "policy", number, 80,
                              f"Número de póliza repetido {n} veces.",
                              {"tipo": "EXACTO", "ocurrencias": n}, {"tipo": "EXACTO", "n": n})

        for key, rows in groups.items():
            rows.sort(key=lambda r: _d(r["start_date"]))
            for a, b in zip(rows, rows[1:]):
                if a["policy_number"] != b["policy_number"] and _d(b["start_date"]) <= _d(a["end_date"]):
                    pair = sorted([str(a["policy_number"]), str(b["policy_number"])])
                    yield Finding(self.code, Severity.MEDIUM, "policy", pair[0], 65,
                                  "Vigencias solapadas para el mismo asegurado, riesgo y ramo.",
                                  {"asegurado": key[0], "riesgo": key[1], "ramo": key[2], "polizas": pair,
                                   "vigencia_a": [str(a["start_date"]), str(a["end_date"])],
                                   "vigencia_b": [str(b["start_date"]), str(b["end_date"])]},
                                  {"polizas": pair})
