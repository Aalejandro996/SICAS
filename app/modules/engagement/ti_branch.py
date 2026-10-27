"""Evaluación TI de la sucursal (Excel «Evaluación_TI_Sucursal», hoja TI_Sucursal).

Cada fila de la cédula es un colaborador entrevistado y responde 20 preguntas SI / NO:
  - Módulo I (TI-01 a TI-15): prácticas de ciberseguridad; «SI» es lo correcto.
  - Módulo II (TI-16 a TI-20): perfiles y segregación de funciones; cualquier «SI» es un conflicto.

Nivel por «SI» del Módulo I (fórmulas del Excel): >= 14 Nivel 1, >= 11 Nivel 2, >= 8 Nivel 3, < 8 Nivel 4.
Nota del colaborador (decisión de Contraloría): % de «SI» del Módulo I; con un conflicto de perfiles queda
limitada al nivel crítico (7 de 15). Nota de la cédula: promedio de los colaboradores.
"""
from __future__ import annotations

MODE = "TI_SUC"
MODULE1_TOTAL = 15
CRITICAL_CAP = round(7 / 15 * 100, 2)          # máximo del Nivel 4
LEVELS = {1: ("NIVEL 1: ÓPTIMO / EXCELENTE", "Riesgo Bajo"), 2: ("NIVEL 2: SATISFACTORIO", "Riesgo Medio-Bajo"),
          3: ("NIVEL 3: REQUIERE MEJORAS", "Riesgo Medio-Alto"), 4: ("NIVEL 4: CRÍTICO / DEFICIENTE", "Riesgo Alto")}
CRITICALITY = {1: "BAJA", 2: "MEDIA", 3: "ALTA", 4: "CRITICA"}
ANSWERS = ("SI", "NO")


def is_ti_criteria(criteria: list[dict]) -> bool:
    return bool(criteria) and all(str(c.get("evaluation_mode") or "").upper() == MODE for c in criteria)


def answer(results: dict, code: str) -> str:
    v = (results or {}).get(code)
    v = v.get("r") if isinstance(v, dict) else v
    v = str(v or "").upper()
    return v if v in ANSWERS else ""


def level_for(yes: float) -> int:
    return 1 if yes >= 14 else 2 if yes >= 11 else 3 if yes >= 8 else 4


def dictamen(yes: float, sod: int) -> str:
    if sod:
        return "RIESGO ELEVADO (Conflicto de Perfiles)"
    return "SATISFACTORIO" if yes >= 8 else "REQUIERE AJUSTES" if yes >= 5 else "RIESGO ELEVADO (Baja Seguridad)"


def evaluate(criteria: list[dict], results: dict) -> dict:
    """Resultado de un colaborador, con las fórmulas de la «Sección exclusiva del auditor» del Excel."""
    m1 = [c for c in criteria if (c.get("module") or "I") == "I"]
    m2 = [c for c in criteria if (c.get("module") or "I") == "II"]
    yes = sum(1 for c in m1 if answer(results, c["code"]) == "SI")
    answered1 = sum(1 for c in m1 if answer(results, c["code"]))
    conflicts = [c["code"] for c in m2 if answer(results, c["code"]) == "SI"]
    answered2 = sum(1 for c in m2 if answer(results, c["code"]))
    if not answered1 and not answered2:
        return {"answered": 0, "total": len(criteria), "yes": 0, "score": None, "level": None, "level_label": None,
                "risk": None, "sod": [], "dictamen": None, "complete": False}
    level = level_for(yes)
    score = round(yes / MODULE1_TOTAL * 100, 2)
    if conflicts:
        score = min(score, CRITICAL_CAP)
    return {"answered": answered1 + answered2, "total": len(criteria), "yes": yes, "score": score, "level": level,
            "level_label": LEVELS[level][0], "risk": LEVELS[level][1], "sod": conflicts, "dictamen": dictamen(yes, len(conflicts)),
            "complete": answered1 + answered2 == len(criteria)}


def item_score(criteria: list[dict], results: dict) -> float | None:
    return evaluate(criteria, results)["score"]


def summary(criteria: list[dict], items: list[dict]) -> dict:
    """Consolidado de la sucursal: promedios, nivel, dictamen y resultado por pregunta."""
    people = []
    for it in items:
        ev = evaluate(criteria, it.get("results") or {})
        name, _, role = str(it.get("ref") or "").partition(" — ")
        people.append({"id": it.get("id"), "ref": it.get("ref"), "name": name, "role": role, **ev,
                       "final": float(it["manual_score"]) if it.get("manual_score") is not None else ev["score"]})
    rated = [p for p in people if p["score"] is not None]
    avg_yes = round(sum(p["yes"] for p in rated) / len(rated), 2) if rated else None
    score = round(sum(p["final"] for p in rated) / len(rated), 2) if rated else None
    sod = sum(1 for p in rated if p["sod"])
    # Nivel de la sucursal según su nota (ya incluye el tope por conflictos de perfiles).
    level = level_for(score / 100 * MODULE1_TOTAL + 1e-9) if score is not None else None
    questions = []
    for c in criteria:
        answers = [answer(it.get("results") or {}, c["code"]) for it in items]
        yes = answers.count("SI")
        no = answers.count("NO")
        bad = no if (c.get("module") or "I") == "I" else yes
        questions.append({"code": c["code"], "number": c.get("number") or c["code"], "module": c.get("module") or "I",
                          "topic": c.get("topic") or "", "text": c.get("text") or "", "iso": c.get("iso") or "",
                          "cobit": c.get("cobit") or "", "yes": yes, "no": no, "failed": bad,
                          "fail_rate": round(bad / (yes + no) * 100, 2) if yes + no else None})
    return {"collaborators": len(people), "rated": len(rated), "people": people, "score": score,
            "module1_pct": round(avg_yes / MODULE1_TOTAL * 100, 2) if avg_yes is not None else None, "avg_yes": avg_yes,
            "level": level, "level_label": LEVELS[level][0] if level else None, "risk": LEVELS[level][1] if level else None,
            "criticality": CRITICALITY[level] if level else None, "sod_conflicts": sod,
            "dictamen": dictamen(avg_yes, sod) if avg_yes is not None else None, "questions": questions}


def findings(ws: dict) -> list[dict]:
    """Hallazgos automáticos de la cédula: prácticas de ciberseguridad débiles y conflictos de perfiles."""
    s = summary(ws.get("criteria") or [], ws.get("items") or [])
    if not s["rated"]:
        return []
    out = []
    weak = [q for q in s["questions"] if q["module"] == "I" and q["failed"]]
    if weak:
        risk = "ALTO" if s["level"] in (3, 4) else "MEDIO" if s["level"] == 2 else "BAJO"
        out.append({
            "rule_key": f"ti_suc:{ws['id']}:ciber", "topic": "tecnologia_sucursal", "risk": risk,
            "title": "Prácticas de ciberseguridad y protección de información por mejorar en la sucursal",
            "condition": f"En la evaluación TI, {s['rated']} colaborador(es) entrevistados obtuvieron en promedio "
                         f"{s['avg_yes']:.1f} de 15 prácticas cumplidas ({s['level_label']}). Puntos incumplidos: "
                         + "; ".join(f"{q['number']}. {q['topic']} ({q['failed']} de {q['yes'] + q['no']})" for q in weak) + ".",
            "criteria": "; ".join(sorted({q["iso"] for q in weak})) + ". " + "; ".join(sorted({q["cobit"] for q in weak})) + ".",
            "cause": "Controles técnicos no configurados en los equipos o prácticas de seguridad no adoptadas por el personal.",
            "effect": "Exposición de la información a accesos no autorizados, fuga de datos o código malicioso.",
            "recommendation": "Configurar los controles técnicos señalados en los equipos de la sucursal y reforzar la "
                              "concienciación del personal en las políticas de ciberseguridad.",
            "controls": [q["code"] for q in weak], "item_id": None, "covered_items": [],
        })
    if s["sod_conflicts"]:
        people = [p for p in s["people"] if p["sod"]]
        out.append({
            "rule_key": f"ti_suc:{ws['id']}:sod", "topic": "tecnologia_sucursal", "risk": "ALTO",
            "title": "Conflictos de perfiles y segregación de funciones en la sucursal",
            "condition": f"{len(people)} colaborador(es) presentan conflicto de roles: "
                         + "; ".join(f"{p['ref']} (preguntas {', '.join(c.replace('TI-', '') for c in p['sod'])})" for p in people) + ".",
            "criteria": "ISO/IEC 27001:2022 A.5.3 (segregación de funciones), A.5.16 (gestión de identidades) y A.5.18 "
                        "(derechos de acceso). COBIT 2019 DSS05.04 y DSS06.03.",
            "cause": "Perfiles de acceso no depurados, usuarios compartidos o permisos que permiten registrar y aprobar el mismo trámite.",
            "effect": "Riesgo de operaciones no autorizadas o fraude sin control por oposición de intereses.",
            "recommendation": "Revisar y depurar los perfiles de los colaboradores señalados, retirar los permisos de cargos "
                              "anteriores y separar las funciones de registro y aprobación.",
            "controls": sorted({c for p in people for c in p["sod"]}), "item_id": None, "covered_items": [],
        })
    return out
