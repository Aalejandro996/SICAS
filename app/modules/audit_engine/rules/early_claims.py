from __future__ import annotations

from typing import Iterator

from ..models import Finding, Severity
from .base import Rule
from .duplicates import _d


class EarlyClaimRule(Rule):
    """
    EARLY-CLAIM:
      - Siniestro con ocurrencia ANTES del inicio o DESPUÉS del fin de vigencia -> CRITICAL.
      - Siniestro dentro de los primeros N días de vigencia -> HIGH (<= high_days) / MEDIUM (<= medium_days).
      - Opcional: cerca del vencimiento (last_days), útil para renovaciones no pagadas.
      - Reporte tardío (reported - occurrence > late_report_days) sube el score.
    Los umbrales son punto de partida: calibrar por ramo con datos históricos.
    """
    code = "EARLY-CLAIM"
    title = "Siniestros cercanos al inicio de vigencia o fuera de ella"
    default_params = {"high_days": 7, "medium_days": 30, "last_days": 0, "late_report_days": 30}

    def run(self, ctx) -> Iterator[Finding]:
        hi, med = int(self.params["high_days"]), int(self.params["medium_days"])
        last, late = int(self.params["last_days"]), int(self.params["late_report_days"])
        for c in ctx.claims():
            if c.get("policy_start") is None:        # póliza inexistente en los datos cargados
                yield Finding(self.code, Severity.HIGH, "claim", str(c["claim_number"]), 85,
                              "Siniestro asociado a una póliza que no existe en los datos cargados.",
                              {"poliza": c["policy_number"], "monto": str(c["claimed_amount"])},
                              {"tipo": "HUERFANO", "poliza": c["policy_number"]})
                continue
            occ, start, end = _d(c["occurrence_date"]), _d(c["policy_start"]), _d(c["policy_end"])
            since_start, to_end = (occ - start).days, (end - occ).days
            delay = (_d(c["reported_date"]) - occ).days
            ev = {"poliza": c["policy_number"], "ocurrencia": str(occ), "inicio_vigencia": str(start),
                  "fin_vigencia": str(end), "dias_desde_inicio": since_start,
                  "dias_hasta_fin": to_end, "dias_hasta_reporte": delay,
                  "monto": float(c["claimed_amount"])}
            sev = score = msg = None
            if since_start < 0 or to_end < 0:
                sev, score, msg = Severity.CRITICAL, 95, "Siniestro con fecha de ocurrencia fuera de la vigencia de la póliza."
            elif since_start <= hi:
                sev, score, msg = Severity.HIGH, 80, f"Siniestro a {since_start} día(s) del inicio de vigencia."
            elif since_start <= med:
                sev, score, msg = Severity.MEDIUM, 55, f"Siniestro a {since_start} día(s) del inicio de vigencia."
            elif last and to_end <= last:
                sev, score, msg = Severity.LOW, 35, f"Siniestro a {to_end} día(s) del vencimiento."
            if sev is None:
                continue
            if delay > late and sev != Severity.CRITICAL:
                score = min(100, score + 10)
                msg += f" Reportado {delay} días después."
            yield Finding(self.code, sev, "claim", str(c["claim_number"]), score, msg, ev,
                          {"poliza": c["policy_number"], "ocurrencia": str(occ)})
