"""KPIs de auditoría y desempeño técnico. `build_kpis` es pura: recibe agregados y devuelve indicadores."""
from __future__ import annotations

from . import calculations as C


def build_kpis(*, written_premium, earned_premium, paid_claims, reserve_start, reserve_end,
               expenses, claim_count: int, exposed_policies: int, findings_by_severity: dict[str, int],
               findings_open: int, findings_closed_30d: int) -> dict:
    incurred = C.incurred_claims(paid_claims, reserve_end, reserve_start)
    total = sum(findings_by_severity.values())
    return {
        "prima_emitida": str(C.money(written_premium)),
        "prima_devengada": str(C.money(earned_premium)),
        "siniestros_incurridos": str(incurred),
        "siniestralidad": _s(C.loss_ratio(incurred, earned_premium)),
        "ratio_gastos": _s(C.expense_ratio(expenses, earned_premium)),
        "ratio_combinado": _s(C.combined_ratio(incurred, expenses, earned_premium)),
        **{k: _s(v) if not isinstance(v, (int, type(None))) else v
           for k, v in C.severity_frequency(paid_claims, claim_count, exposed_policies).items()},
        "hallazgos": {"total": total, "abiertos": findings_open, "cerrados_30d": findings_closed_30d,
                      "por_severidad": findings_by_severity,
                      "criticos_y_altos_pct": _s(C.ratio(findings_by_severity.get("CRITICAL", 0)
                                                         + findings_by_severity.get("HIGH", 0), total))},
    }


def _s(v):
    return None if v is None else str(v)
