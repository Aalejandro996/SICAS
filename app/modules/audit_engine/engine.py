from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .context import DataContext
from .models import Finding, Severity
from .rules.base import Rule
from .rules.benford import BenfordRule
from .rules.duplicates import DuplicateClaimsRule, OverlappingPoliciesRule
from .rules.early_claims import EarlyClaimRule
from .rules.lcft import CashThresholdRule, StructuringRule, WatchlistRule
from .rules.reserves_range import ReserveRangeRule

REGISTRY: dict[str, type[Rule]] = {
    r.code: r for r in (DuplicateClaimsRule, OverlappingPoliciesRule, EarlyClaimRule,
                        ReserveRangeRule, BenfordRule, CashThresholdRule, StructuringRule, WatchlistRule)
}


@dataclass
class EngineResult:
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    params_snapshot: dict[str, Any] = field(default_factory=dict)


def run_engine(ctx: DataContext, params: dict[str, dict] | None = None,
               enabled: set[str] | None = None) -> EngineResult:
    """
    params  : {rule_code: {parametros}} (engine.rule_parameters); lo no indicado usa default_params.
    enabled : códigos a ejecutar (None = todos).
    Una regla que falla no detiene a las demás: se registra en `errors`.
    """
    params = params or {}
    res = EngineResult()
    for code, cls in REGISTRY.items():
        if enabled is not None and code not in enabled:
            continue
        rule = cls(params.get(code))
        res.params_snapshot[code] = rule.params
        t0, count = time.perf_counter(), 0
        try:
            for f in rule.run(ctx):
                res.findings.append(f)
                count += 1
        except Exception as exc:  # noqa: BLE001
            res.errors.append({"rule": code, "error": f"{type(exc).__name__}: {exc}"})
        res.skipped += getattr(rule, "skipped", [])
        res.summary[code] = {"findings": count, "seconds": round(time.perf_counter() - t0, 3)}
    # Dedupe dentro de la corrida por fingerprint
    uniq = {f.fingerprint: f for f in res.findings}
    res.findings = sorted(uniq.values(), key=lambda f: f.score, reverse=True)
    return res


def by_severity(findings: list[Finding]) -> dict[str, int]:
    out = {s.value: 0 for s in Severity}
    for f in findings:
        out[f.severity.value] += 1
    return out
