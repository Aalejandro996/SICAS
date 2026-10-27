"""Evaluación TI de la sucursal: mismas fórmulas que el Excel «Evaluación_TI_Sucursal» (hoja TI_Sucursal)."""
from app.modules.engagement import scoring, ti_branch

CRITERIA = [{"code": f"TI-{i:02d}", "evaluation_mode": "TI_SUC", "module": "I" if i <= 15 else "II", "number": str(i),
             "topic": f"Aspecto {i}", "iso": "ISO", "cobit": "COBIT", "text": f"Pregunta {i}"} for i in range(1, 21)]
EXCEL = "NO SI NO SI SI NO SI NO SI NO NO NO SI NO SI SI SI NO NO SI".split()   # respuestas de ejemplo del Excel


def res(answers):
    return {f"TI-{i:02d}": {"r": a, "c": ""} for i, a in enumerate(answers, 1)}


def test_excel_example_level_risk_and_dictamen():
    ev = ti_branch.evaluate(CRITERIA, res(EXCEL))
    assert ev["yes"] == 7                                      # Excel: «7 / 15»
    assert ev["level_label"] == "NIVEL 4: CRÍTICO / DEFICIENTE" and ev["risk"] == "Riesgo Alto"
    assert ev["sod"] == ["TI-16", "TI-17", "TI-20"]
    assert ev["dictamen"] == "RIESGO ELEVADO (Conflicto de Perfiles)"


def test_levels_follow_the_excel_thresholds():
    for yes, level in ((15, 1), (14, 1), (13, 2), (11, 2), (10, 3), (8, 3), (7, 4), (0, 4)):
        assert ti_branch.level_for(yes) == level


def test_score_is_module1_and_sod_caps_it_at_critical():
    clean = ["SI"] * 15 + ["NO"] * 5
    assert scoring.item_score(CRITERIA, res(clean)) == 100.0
    conflict = ["SI"] * 15 + ["SI"] + ["NO"] * 4
    assert scoring.item_score(CRITERIA, res(conflict)) == ti_branch.CRITICAL_CAP == 46.67


def test_dictamen_without_conflicts():
    assert ti_branch.dictamen(8, 0) == "SATISFACTORIO"
    assert ti_branch.dictamen(5, 0) == "REQUIERE AJUSTES"
    assert ti_branch.dictamen(4, 0) == "RIESGO ELEVADO (Baja Seguridad)"


def test_branch_summary_and_findings():
    items = [{"id": "a", "ref": "Ana — Cajera", "results": res(EXCEL)},
             {"id": "b", "ref": "Luis — Analista", "results": res(["SI"] * 15 + ["NO"] * 5)}]
    s = ti_branch.summary(CRITERIA, items)
    assert s["rated"] == 2 and s["sod_conflicts"] == 1 and s["score"] == round((46.67 + 100) / 2, 2)
    assert scoring.worksheet_summary(CRITERIA, items).auto == s["score"]
    keys = [f["rule_key"].split(":")[-1] for f in ti_branch.findings({"id": "w", "criteria": CRITERIA, "items": items})]
    assert keys == ["ciber", "sod"]


def test_unanswered_collaborator_has_no_score():
    assert ti_branch.evaluate(CRITERIA, {})["score"] is None
