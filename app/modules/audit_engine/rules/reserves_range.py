from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Iterator

from app.modules.analytics.calculations import D

from ..models import Finding, Severity
from .base import Rule


def modified_z_scores(values: list[float]) -> list[float]:
    """Z modificado (Iglewicz-Hoaglin) basado en mediana/MAD: robusto ante los propios valores atípicos."""
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    if mad > 0:
        return [0.6745 * (v - med) / mad for v in values]
    mean_ad = statistics.fmean([abs(v - med) for v in values])   # respaldo cuando MAD = 0
    if mean_ad == 0:
        return [0.0 for _ in values]
    return [(v - med) / (1.253314 * mean_ad) for v in values]


class ReserveRangeRule(Rule):
    """
    RESERVE-RANGE — tres controles:
      1. Reserva negativa.
      2. Reserva por encima de max_ratio * suma asegurada (según tipo de reserva).
      3. Rangos absolutos por 'TIPO:RAMO' o 'RAMO' (parametrizables por Contraloría).
      4. Atípicos estadísticos por (tipo, ramo, moneda): z modificado de log10(monto) > z_threshold (mín. min_group_size registros).
    """
    code = "RESERVE-RANGE"
    title = "Reservas fuera de rango"
    default_params = {
        "max_ratio": {"CLAIM": 1.0, "MATHEMATICAL": 1.0},
        "absolute_ranges": {},          # {"CLAIM:AUTO": {"min": 0, "max": 5_000_000}}
        "z_threshold": 3.5, "z_high": 6.0, "min_group_size": 30,
    }

    def run(self, ctx) -> Iterator[Finding]:
        p = self.params
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for i, r in enumerate(ctx.reserves()):
            r = dict(r)
            r["_id"] = r.get("claim_number") or r.get("policy_number") or f"row{i}"
            amount = float(r["amount"])
            rtype, branch = r["reserve_type"], r["branch"]
            base = {"tipo": rtype, "ramo": branch, "periodo": str(r["period"]), "monto": amount}

            if amount < 0:
                yield Finding(self.code, Severity.HIGH, "reserve", str(r["_id"]), 85,
                              "Reserva con monto negativo.", base, {"control": "NEG", "periodo": str(r["period"]), "tipo": rtype})
            ratio = (p["max_ratio"] or {}).get(rtype)
            si = r.get("sum_insured")
            if ratio and si and D(si) > 0 and D(amount) > D(ratio) * D(si):
                yield Finding(self.code, Severity.HIGH, "reserve", str(r["_id"]), 90,
                              f"Reserva excede {ratio:.0%} de la suma asegurada.",
                              {**base, "suma_asegurada": float(si), "razon": float(D(amount) / D(si))},
                              {"control": "RATIO", "periodo": str(r["period"]), "tipo": rtype})
            rng = p["absolute_ranges"].get(f"{rtype}:{branch}") or p["absolute_ranges"].get(branch)
            if rng and not (rng.get("min", float("-inf")) <= amount <= rng.get("max", float("inf"))):
                yield Finding(self.code, Severity.MEDIUM, "reserve", str(r["_id"]), 70,
                              "Reserva fuera del rango autorizado para el ramo.",
                              {**base, "rango": rng}, {"control": "RANGE", "periodo": str(r["period"]), "tipo": rtype})
            groups[(rtype, branch, r.get("currency"))].append(r)

        for (rtype, branch, cur), rows in groups.items():
            # Los montos son asimétricos (cola larga): el z robusto se calcula sobre log10(monto), así la cola
            # derecha natural no se marca como atípica. Los montos <= 0 ya los cubre el control de negativos.
            rows = [r for r in rows if float(r["amount"]) > 0]
            if len(rows) < int(p["min_group_size"]):
                continue
            zs = modified_z_scores([math.log10(float(r["amount"])) for r in rows])
            for r, z in zip(rows, zs):
                if abs(z) >= float(p["z_threshold"]):
                    sev = Severity.HIGH if abs(z) >= float(p["z_high"]) else Severity.MEDIUM
                    yield Finding(self.code, sev, "reserve", str(r["_id"]), min(100, 50 + abs(z) * 5),
                                  f"Reserva atípica dentro de su grupo ({rtype}/{branch}/{cur}), z modificado (log) = {z:.1f}.",
                                  {"tipo": rtype, "ramo": branch, "periodo": str(r["period"]),
                                   "monto": float(r["amount"]), "z_modificado": round(z, 2),
                                   "n_grupo": len(rows)},
                                  {"control": "ZSCORE", "periodo": str(r["period"]), "tipo": rtype})
