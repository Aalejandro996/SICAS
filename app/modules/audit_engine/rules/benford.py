from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Iterator

from ..models import Finding, Severity
from .base import Rule

BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
CHI2_CRIT_8DF = {0.05: 15.507, 0.01: 20.090}   # gl = 8 (9 dígitos - 1)


def first_digit(x: float, min_value: float) -> int | None:
    try:
        x = float(x)
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(x):
        return None

    x = abs(x)
    if x < min_value or x == 0:
        return None
    return int(f"{x:e}"[0])


def benford_stats(values: list[float], min_value: float = 10.0) -> dict | None:
    digits = [
        d for d in (first_digit(v, min_value) for v in values)
        if d is not None
    ]
    n = len(digits)
    if n == 0:
        return None
    counts = Counter(digits)
    rows, mad, chi2 = [], 0.0, 0.0
    for d in range(1, 10):
        obs, exp = counts.get(d, 0) / n, BENFORD[d]
        mad += abs(obs - exp) / 9
        chi2 += (counts.get(d, 0) - n * exp) ** 2 / (n * exp)
        # z por dígito con corrección de continuidad (Nigrini)
        z = (abs(obs - exp) - 1 / (2 * n)) / math.sqrt(exp * (1 - exp) / n)
        rows.append({"digito": d, "observado": round(obs, 4), "esperado": round(exp, 4),
                     "z": round(max(z, 0.0), 2)})
    return {"n": n, "mad": round(mad, 5), "chi2": round(chi2, 2), "digitos": rows}


def mad_conformity(mad: float) -> str:
    """Umbrales de Nigrini para primer dígito."""
    if mad <= 0.006: return "CONFORME"
    if mad <= 0.012: return "ACEPTABLE"
    if mad <= 0.015: return "MARGINAL"
    return "NO_CONFORME"


class BenfordRule(Rule):
    """
    BENFORD-1D: compara la distribución del primer dígito de los montos con la ley de Benford.
    Es una SEÑAL para dirigir el muestreo, no una prueba de fraude. Se informa solo si la MAD indica no conformidad
    Y el chi-cuadrado es significativo (con n pequeño la MAD sola produce falsos positivos por ruido de muestreo). Se omiten grupos con pocos datos
    o con rango dinámico insuficiente (Benford exige montos que abarquen varios órdenes de magnitud).
    """
    code = "BENFORD-1D"
    title = "Desviación de la ley de Benford (primer dígito)"
    default_params = {
        "sources": [
            {"dataset": "claims", "field": "claimed_amount", "group_by": "branch"},
            {"dataset": "reserves", "field": "amount", "group_by": "reserve_type"},
        ],
        "min_sample": 300, "min_value": 10.0, "min_magnitude_ratio": 100,
        "min_chi2": 20.09,          # además de la MAD se exige significancia (gl=8, 1 %): evita falsos positivos con n pequeño
        "period_label": None,
    }

    def __init__(self, params=None):
        super().__init__(params)
        self.skipped: list[dict] = []

    def run(self, ctx) -> Iterator[Finding]:
        self.skipped = []
        p = self.params
        min_sample = int(p["min_sample"])
        min_value = float(p["min_value"])
        min_ratio = float(p["min_magnitude_ratio"])

        if min_sample < 1 or not math.isfinite(min_value) or min_value < 0:
            raise ValueError("Parámetros Benford inválidos: min_sample/min_value.")
        if not math.isfinite(min_ratio) or min_ratio <= 0:
            raise ValueError("Parámetro Benford inválido: min_magnitude_ratio.")

        for src in p["sources"]:
            rows = getattr(ctx, src["dataset"])()
            groups: dict[str, list[float]] = defaultdict(list)
            invalid_counts: dict[str, int] = defaultdict(int)

            for r in rows:
                g = str(r.get(src["group_by"], "TODOS")) if src.get("group_by") else "TODOS"
                if r.get("currency"):
                    g += "/" + str(r["currency"])

                try:
                    value = float(r.get(src["field"]))
                except (TypeError, ValueError, OverflowError):
                    invalid_counts[g] += 1
                    continue

                if not math.isfinite(value):
                    invalid_counts[g] += 1
                    continue

                groups[g].append(value)

            for group, invalid_count in invalid_counts.items():
                label = f"{src['dataset']}.{src['field']}[{group}]"
                self.skipped.append({
                    "grupo": label,
                    "motivo": (
                        f"se omitieron {invalid_count} importe(s) "
                        "no numérico(s) o no finito(s)"
                    ),
                })

            for group, values in groups.items():
                label = f"{src['dataset']}.{src['field']}[{group}]"
                positives = [
                    abs(v) for v in values
                    if v != 0 and abs(v) >= min_value
                ]
                if len(positives) < min_sample:
                    self.skipped.append({"grupo": label, "motivo": f"muestra insuficiente ({len(positives)} < {p['min_sample']})"})
                    continue
                if max(positives) / min(positives) < min_ratio:
                    self.skipped.append({"grupo": label, "motivo": "rango dinámico insuficiente para Benford"})
                    continue
                st = benford_stats(values, min_value)
                level = mad_conformity(st["mad"])
                if level in ("CONFORME", "ACEPTABLE") or st["chi2"] < p["min_chi2"]:
                    continue
                sev = Severity.LOW if level == "MARGINAL" else (Severity.MEDIUM if st["mad"] <= 0.025 else Severity.HIGH)
                top = sorted(st["digitos"], key=lambda d: d["z"], reverse=True)[:3]
                yield Finding(self.code, sev, "dataset", label, min(100, 40 + st["mad"] * 2000),
                              f"Distribución del primer dígito {level.replace('_', ' ').lower()} con Benford "
                              f"(MAD={st['mad']}, n={st['n']}).",
                              {"conformidad": level, "n": st["n"], "mad": st["mad"], "chi2": st["chi2"],
                               "chi2_critico_5pct": CHI2_CRIT_8DF[0.05], "chi2_critico_1pct": CHI2_CRIT_8DF[0.01],
                               "digitos_mas_desviados": top, "distribucion": st["digitos"]},
                              {"periodo": p.get("period_label"), "nivel": level})
