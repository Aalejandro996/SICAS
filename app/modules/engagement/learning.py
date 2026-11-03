"""Retroalimentación del motor de reglas (lógica pura, explicable y bajo control humano).

El motor NO se modifica solo. Aprende de cuatro fuentes y deja todo trazado:
1. Decisiones del auditor: acepta, edita o descarta un hallazgo automático, cambia su riesgo o reescribe una
   conclusión (engagement.engine_feedback).
2. Historial: un control que falla en varias auditorías o aplicativos sube un punto de probabilidad en la matriz de
   riesgos; uno conforme de forma sostenida baja un punto. En todos los dominios (Sistemas, Operativa, Financiera,
   Administrativa, Especial), un hallazgo automático cuyo tema ya se observó en auditorías cerradas de la misma unidad
   se marca como reiterado y, si se repite en dos o más, sube un nivel de riesgo. Cada ajuste lleva su explicación.
3. Redacción sugerida: condición, causa y recomendación de hallazgos parecidos ya aprobados (similitud de términos).
4. Reglas propuestas: cuando un patrón se repite, el motor plantea la regla con su evidencia; solo el Contralor la
   aprueba (queda quién y cuándo) y recién entonces se aplica.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

FEEDBACK_KINDS = {
    "OBS_ACCEPTED": "Hallazgo automático aceptado",
    "OBS_EDITED": "Hallazgo automático editado",
    "OBS_DISCARDED": "Hallazgo automático descartado",
    "RISK_CHANGED": "Nivel de riesgo cambiado",
    "CONCLUSION_REWRITTEN": "Conclusión reescrita",
    "RISK_MATRIX_OVERRIDE": "Probabilidad / impacto ajustados en la matriz",
    "MATURITY_OVERRIDE": "Madurez ajustada por el auditor",
}
PROPOSAL_KINDS = {
    "WEIGHT": "Elevar el peso de un control",
    "RISK": "Nivel de riesgo por defecto de un tema",
    "RECOMMEND": "Recomendación por defecto de un tema",
    "SUPPRESS": "Dejar de redactar automáticamente un tema",
}
RISK_LEVELS = ("BAJO", "MEDIO", "ALTO")
MAX_TEXT = 3000          # largo máximo de la condición (el mismo que valida la edición)
MIN_EVIDENCE = 3          # repeticiones mínimas para proponer una regla
HISTORY_WINDOW = 5        # resultados recientes por control que se consideran
FINDING_FIELDS = ("title", "condition", "criteria", "cause", "effect", "recommendation")

STOP = set("""a al algo algun alguna algunas alguno algunos ante antes como con contra cual cuando de del desde donde durante
e el ella ellas ellos en entre era es esa esas ese eso esos esta estan estas este esto estos fue fueron ha han hasta hay la
las le les lo los mas me mi muy no nos o otra otro para pero por que se sea segun ser si sin sobre su sus tambien te tiene
tienen un una uno unos y ya control controles sistema area existe existen se debe deben""".split())


def pattern_key(rule_key: str | None, controls=None) -> str | None:
    """Clave del patrón al que pertenece un hallazgo automático (tema normativo, dominio o control)."""
    rk = str(rule_key or "")
    if rk.startswith(("sis:", "app:")):
        return rk
    if rk.startswith("ti_suc:"):
        return "ti_suc:" + rk.rsplit(":", 1)[-1]
    if rk:
        return "sudeaseg:" + rk.rsplit(":", 1)[-1]
    codes = [c for c in (controls or []) if c]
    return f"ctrl:{codes[0]}" if len(codes) == 1 else None


def pattern_label(key: str | None) -> str:
    """Nombre legible del patrón para las propuestas y la bitácora."""
    k = str(key or "")
    prefix, _, rest = k.partition(":")
    rest = rest.replace("_", " ")
    return {"sis": f"Sistemas — {rest}", "app": f"Aplicativo — {rest}", "sudeaseg": f"Normativa SUDEASEG — {rest}",
            "ti_suc": f"Evaluación TI de sucursal — {rest}", "ctrl": f"control {rest}", "madurez": f"madurez {rest}",
            "conclusion": f"conclusión del informe {rest.lower()}"}.get(prefix, k)


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", _norm(text)) if w not in STOP}


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ------------------------------------------------------------------ 2. historial de controles
def history_adjustments(rows: list[dict], window: int = HISTORY_WINDOW) -> dict:
    """Ajuste de probabilidad por control a partir de auditorías cerradas.

    rows: {"control", "conforme" (bool), "audit_code", "app", "closed_at"} de auditorías CERRADAS (sin la actual).
    +1 si falló en al menos 2 de sus últimas `window` evaluaciones y en al menos la mitad;
    -1 si sus últimas 3 evaluaciones (o más) son todas conformes. Sin historial suficiente, 0.
    """
    by_ctrl: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ctrl[r["control"]].append(r)
    out = {}
    for ctrl, rs in by_ctrl.items():
        rs = sorted(rs, key=lambda r: str(r.get("closed_at") or ""), reverse=True)[:window]
        fails = [r for r in rs if not r["conforme"]]
        apps = sorted({str(r.get("app") or "") for r in fails if r.get("app")})
        if len(fails) >= 2 and len(fails) * 2 >= len(rs):
            out[ctrl] = {"delta": 1, "evaluations": len(rs), "fails": len(fails),
                         "reason": f"Falló en {len(fails)} de sus últimas {len(rs)} evaluaciones"
                                   + (f" ({len(apps)} aplicativo(s): {', '.join(apps)})" if apps else "")
                                   + ": la probabilidad sube un punto.",
                         "audits": [r.get("audit_code") for r in fails]}
        elif len(rs) >= 3 and not fails:
            out[ctrl] = {"delta": -1, "evaluations": len(rs), "fails": 0,
                         "reason": f"Conforme en sus últimas {len(rs)} evaluaciones: la probabilidad baja un punto.",
                         "audits": [r.get("audit_code") for r in rs]}
    return out


def recurrence(draft: dict, history: list[dict], window: int = HISTORY_WINDOW) -> dict:
    """Marca como reiterado un hallazgo automático cuyo tema ya se observó en auditorías cerradas de la unidad.

    history: {"pattern_key", "audit_code", "closed_at"} de observaciones vigentes de auditorías CERRADAS de la misma
    unidad (sin la actual). Se miran las últimas `window` auditorías de la unidad. Una aparición previa deja la nota;
    dos o más suben el riesgo un nivel (BAJO→MEDIO→ALTO). El auditor puede cambiarlo y eso también se aprende.
    """
    key = pattern_key(draft.get("rule_key"), draft.get("controls"))
    if not key or not history:
        return draft
    recent = []
    for r in sorted(history, key=lambda r: str(r.get("closed_at") or ""), reverse=True):
        if r.get("audit_code") not in recent:
            recent.append(r.get("audit_code"))
    recent = recent[:window]
    seen = sorted({r.get("audit_code") for r in history if r.get("audit_code") in recent and r.get("pattern_key") == key})
    if not seen:
        return draft
    out = dict(draft)
    risk = out.get("risk") if out.get("risk") in RISK_LEVELS else "MEDIO"
    delta = 1 if len(seen) >= 2 and risk != "ALTO" else 0
    if delta:
        out["risk"] = RISK_LEVELS[RISK_LEVELS.index(risk) + 1]
    reason = (f"Observación reiterada: el mismo tema se observó en {len(seen)} de las últimas {len(recent)} auditorías cerradas "
              f"de la unidad ({', '.join(seen)})" + (f"; el riesgo sube de {risk} a {out['risk']}." if delta else "."))
    base = str(out.get("condition") or "")
    room = MAX_TEXT - len(reason) - 2
    out["condition"] = (base if len(base) <= room else base[: room - 1].rstrip() + "…") + "\n\n" + reason
    out["history"] = {"audits": seen, "window": len(recent), "delta": delta, "reason": reason}
    return out


# ------------------------------------------------------------------ 3. redacción sugerida
def suggestions(target: dict, approved: list[dict], limit: int = 3) -> list[dict]:
    """Hallazgos aprobados más parecidos al indicado (título + condición), con bonificación por mismo tema o control.

    approved: observaciones de auditorías con informe final aprobado/firmado (de otras auditorías).
    """
    key = pattern_key(target.get("rule_key"), target.get("controls"))
    base = f"{target.get('title') or ''} {target.get('condition') or ''}"
    scored = []
    for o in approved:
        if str(o.get("id")) == str(target.get("id")):
            continue
        s = similarity(base, f"{o.get('title') or ''} {o.get('condition') or ''}")
        same = key and pattern_key(o.get("rule_key"), o.get("controls")) == key
        s = s + (0.25 if same else 0.0)
        if s >= 0.12:
            scored.append((s, o))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for s, o in scored:
        sig = (o.get("cause") or "")[:80] + "|" + (o.get("recommendation") or "")[:80]
        if sig in seen:
            continue
        seen.add(sig)
        out.append({"id": o.get("id"), "audit_code": o.get("audit_code"), "title": o.get("title"), "risk": o.get("risk"),
                    "condition": o.get("condition"), "cause": o.get("cause"), "recommendation": o.get("recommendation"),
                    "effect": o.get("effect"), "similarity": round(min(s, 1.0) * 100), "same_topic": bool(key and s >= 0.25
                    and pattern_key(o.get("rule_key"), o.get("controls")) == key)})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ 4. reglas propuestas
def _evidence(events: list[dict]) -> list[dict]:
    return [{"audit_code": e.get("audit_code"), "at": str(e.get("created_at") or "")[:16], "by": e.get("user_name"),
             "before": e.get("before"), "after": e.get("after")} for e in events][:20]


def propose(feedback: list[dict], history_rows: list[dict], weights: dict, existing: set[tuple[str, str]],
            min_evidence: int = MIN_EVIDENCE, pattern_rows: list[dict] | None = None) -> list[dict]:
    """Reglas nuevas a partir de patrones repetidos. Nunca se activan solas.

    feedback: eventos de engine_feedback (kind, pattern_key, before, after, audit_code, user_name, created_at).
    history_rows: igual que history_adjustments, con "template" (ACSELX, SISTEMAS/ERP_TI, LCFT/GENERAL…) de todas las
        auditorías cerradas; "pattern_rows": {"pattern_key", "audit_code", "unit"} de sus hallazgos vigentes.
    weights: peso vigente por control {"ACSELX:SEG04": 1, "SISTEMAS/ERP_TI:TI005": 1}.
    existing: (tipo, objetivo) de propuestas pendientes o reglas ya activas (no se repiten).
    """
    out = []

    def add(kind, target, value, rationale, ev):
        if (kind, target) in existing:
            return
        existing.add((kind, target))
        out.append({"kind": kind, "target": target, "value": value, "rationale": rationale, "evidence": ev})

    # WEIGHT: control que falla en N auditorías distintas y todavía no es crítico.
    fails = defaultdict(set)
    for r in history_rows:
        if not r["conforme"]:
            fails[f"{r.get('template') or 'ACSELX'}:{r['control']}"].add(r.get("audit_code"))
    for target, audits in sorted(fails.items()):
        if len(audits) >= min_evidence and int(weights.get(target, 1)) < 3:
            add("WEIGHT", target, {"weight": 3},
                f"El criterio {target.split(':', 1)[1]} de {template_label(target)} no se cumplió en {len(audits)} auditorías "
                f"cerradas: se propone marcarlo como crítico (peso 3), con lo que pesa más en la calificación de las próximas "
                f"cédulas.", [{"audit_code": a} for a in sorted(a for a in audits if a)])

    # RISK sistémico: el mismo tema se observa en varias auditorías cerradas de distintas unidades.
    audits_by_key, units_by_key = defaultdict(set), defaultdict(set)
    for r in pattern_rows or []:
        k = r.get("pattern_key")
        if k and not k.startswith(("ti_suc:", "ctrl:")):
            audits_by_key[k].add(r.get("audit_code"))
            units_by_key[k].add(r.get("unit"))
    for key, audits in sorted(audits_by_key.items()):
        units = sorted(u for u in units_by_key[key] if u)
        if len(audits) >= min_evidence and len(units) >= 2:
            add("RISK", key, {"risk": "ALTO"},
                f"«{pattern_label(key)}» se observó en {len(audits)} auditorías cerradas de {len(units)} unidades "
                f"({', '.join(units[:6])}{'…' if len(units) > 6 else ''}): es una debilidad sistémica y se propone que el motor "
                f"redacte esos hallazgos con riesgo ALTO.", [{"audit_code": a} for a in sorted(a for a in audits if a)][:20])

    by_key = defaultdict(list)
    for e in feedback:
        if e.get("pattern_key"):
            by_key[(e["kind"], e["pattern_key"])].append(e)

    # RISK: el auditor cambia el riesgo de un mismo tema al mismo nivel, una y otra vez.
    for (kind, key), evs in sorted(by_key.items()):
        if kind != "RISK_CHANGED":
            continue
        levels = Counter(str((e.get("after") or {}).get("risk") or "") for e in evs)
        level, n = levels.most_common(1)[0] if levels else ("", 0)
        if level and n >= min_evidence and n * 3 >= len(evs) * 2:
            add("RISK", key, {"risk": level},
                f"En {n} de {len(evs)} ocasiones el auditor cambió el riesgo de los hallazgos de «{pattern_label(key)}» a {level}: "
                f"se propone que el motor los redacte con ese nivel.", _evidence(evs))

    # RECOMMEND: el auditor reescribe la recomendación de un mismo tema.
    for (kind, key), evs in sorted(by_key.items()):
        if kind != "OBS_EDITED":
            continue
        recs = [str((e.get("after") or {}).get("recommendation") or "").strip() for e in evs]
        recs = [r for r in recs if len(r) >= 30]
        if len(recs) >= min_evidence:
            # Se propone la redacción más representativa: la que más se parece al resto.
            best = max(recs, key=lambda r: sum(similarity(r, o) for o in recs))
            add("RECOMMEND", key, {"recommendation": best},
                f"El auditor reescribió la recomendación de «{pattern_label(key)}» en {len(recs)} hallazgos: se propone usar como "
                f"recomendación por defecto la redacción más representativa.", _evidence(evs))

    # SUPPRESS: el auditor descarta una y otra vez el hallazgo automático de un tema.
    for (kind, key), evs in sorted(by_key.items()):
        if kind != "OBS_DISCARDED":
            continue
        accepted = len(by_key.get(("OBS_ACCEPTED", key), []))
        if len(evs) >= min_evidence and len(evs) > 2 * accepted:
            add("SUPPRESS", key, {"suppress": True},
                f"El hallazgo automático de «{pattern_label(key)}» fue descartado {len(evs)} veces y aceptado {accepted}: se propone "
                f"dejar de redactarlo automáticamente (el auditor puede registrarlo a mano).", _evidence(evs))
    return out


def template_label(target: str) -> str:
    """«SISTEMAS/ERP_TI:TI005» → «la cédula SISTEMAS / ERP_TI»; «ACSELX:SEG04» → «la plantilla ACSELX»."""
    tpl = str(target or "").split(":", 1)[0]
    return f"la cédula {tpl.replace('/', ' / ')}" if "/" in tpl else f"la plantilla {tpl}"


def template_weights(rules: dict, template: str) -> dict:
    """Pesos aprobados {código: peso} de una plantilla a partir de las reglas WEIGHT vigentes."""
    return {t.split(":", 1)[1]: int(v.get("weight", 1)) for (k, t), v in rules.items()
            if k == "WEIGHT" and t.startswith(f"{template}:")}


def apply_rules(draft: dict, rules: dict) -> dict | None:
    """Aplica las reglas APROBADAS a un hallazgo automático. None si una regla lo suprime.

    rules: {(tipo, objetivo): valor} de engagement.engine_rules activas.
    """
    key = pattern_key(draft.get("rule_key"), draft.get("controls"))
    if not key:
        return draft
    if rules.get(("SUPPRESS", key)):
        return None
    out = dict(draft)
    applied = []
    risk = (rules.get(("RISK", key)) or {}).get("risk")
    if risk in ("ALTO", "MEDIO", "BAJO") and risk != out.get("risk"):
        out["risk"] = risk
        applied.append("RISK")
    rec = (rules.get(("RECOMMEND", key)) or {}).get("recommendation")
    if rec:
        out["recommendation"] = rec
        applied.append("RECOMMEND")
    if applied:
        out["rules_applied"] = applied
    return out


def feedback_summary(events: list[dict]) -> dict:
    counts = Counter(e["kind"] for e in events)
    return {"total": len(events), "by_kind": [{"kind": k, "label": FEEDBACK_KINDS.get(k, k), "count": counts[k]}
                                              for k in FEEDBACK_KINDS if counts.get(k)]}
