"""Auditoría de aplicativos: réplica de la matriz AcselX v2 y encuestas direccionadas."""
from datetime import date

from app.modules.engagement import app_audit as ap
from app.modules.engagement import norms, scoring

# Respuestas de ejemplo de la hoja «Cuestionario AcselX» (C, E, F de las filas 8 a 37).
EXCEL = [("SEG01", "SI", "SI", "ACTUALIZADO"), ("SEG02", "SI", "SI", "ACTUALIZADO"), ("SEG03", "SI", "SI", "ACTUALIZADO"),
         ("SEG04", "NO", "NO", "INEXISTENTE"), ("SEG05", "NO", "NO", "INEXISTENTE"), ("LOG01", "SI", "SI", "ACTUALIZADO"),
         ("LOG02", "NO", "NO", "INEXISTENTE"), ("LOG03", "SI", "SI", "ACTUALIZADO"), ("LOG04", "NO", "NO", "INEXISTENTE"),
         ("LOG05", "SI", "SI", "ACTUALIZADO"), ("BDD01", "NO", "NO", "INEXISTENTE"), ("BDD02", "NO", "NO", "INEXISTENTE"),
         ("BDD03", "SI", "SI", "ACTUALIZADO"), ("BDD04", "NO", "SI", "DESACTUALIZADO"), ("BDD05", "SI", "SI", "ACTUALIZADO"),
         ("CHG01", "SI", "SI", "ACTUALIZADO"), ("CHG02", "NO", "SI", "DESACTUALIZADO"), ("CHG03", "NO", "NO", "INEXISTENTE"),
         ("CHG04", "SI", "SI", "ACTUALIZADO"), ("CHG05", "NO", "NO", "INEXISTENTE"), ("BCP01", "SI", "SI", "ACTUALIZADO"),
         ("BCP02", "NO", "SI", "DESACTUALIZADO"), ("BCP03", "NO", "NO", "INEXISTENTE"), ("BCP04", "SI", "SI", "ACTUALIZADO"),
         ("BCP05", "SI", "SI", "ACTUALIZADO"), ("REG01", "SI", "SI", "ACTUALIZADO"), ("REG02", "SI", "SI", "ACTUALIZADO"),
         ("REG03", "NO", "SI", "DESACTUALIZADO"), ("REG04", "SI", "SI", "DESACTUALIZADO"), ("REG05", "NO", "NO", "INEXISTENTE")]


def items():
    return [{"ref": c, "results": {c: {"control": a, "documental": d, "evidencia": e}}} for c, a, d, e in EXCEL]


def test_template_has_thirty_directed_controls_in_six_blocks():
    crit = ap.criteria("ACSELX")
    assert len(crit) == 30 and len({c["block"] for c in crit}) == 6
    assert all(c["area"] in ap.AREAS and c["evidence_required"] and c["norms"] for c in crit)
    assert scoring.is_system_criteria(crit)          # reutiliza la fórmula y las fases de Sistemas
    assert {c["source_id"] for c in crit} == {f"{b}-ACX-0{i}" for b in ap.BLOCKS for i in range(1, 6)}
    known = {n[0] for n in norms.NORMS}
    assert all(code in known for c in crit for code in c["norms"])


def test_formula_matches_excel_panel():
    crit = ap.criteria()
    ov = ap.overview(crit, items())
    assert ov["conformes"] == 15 and ov["hallazgos"] == 15
    assert ov["cumplimiento_efectivo"] == 50.0
    assert ov["promedio_general"] == 52.8           # =AVERAGE(H8:H37) del Excel: 0,5283
    # La fórmula del motor de Sistemas es la misma que la del Excel.
    for it in items():
        assert scoring.item_score(crit, it["results"]) == ap.control_points(it["results"][it["ref"]])


def test_blocks_and_diagnosis_like_dashboard():
    rows = {b["block"]: b for b in ap.block_summary(ap.criteria(), items())}
    assert rows["SEG"]["conformes"] == 3 and rows["SEG"]["diagnostico"] == "Requiere mejora"
    assert rows["BDD"]["cumplimiento"] == 40.0 and rows["BDD"]["diagnostico"] == "Crítico"
    assert rows["REG"]["conformes"] == 2


def test_risk_matrix_levels_and_history_and_override():
    m = {r["code"]: r for r in ap.risk_matrix("ACSELX", items())}
    assert m["RIE-ACX-01"]["score"] == 20 and m["RIE-ACX-01"]["level"] == "Crítico"     # SEG04 no conforme: 4 x 5
    assert m["RIE-ACX-02"]["level"] == "Bajo" and m["RIE-ACX-02"]["status"].startswith("Mitigado")
    assert m["RIE-ACX-07"]["score"] == 2                                            # REG02 conforme: 1 x 2
    hist = ap.risk_matrix("ACSELX", items(), history={"REG02": {"delta": 1, "reason": "x"}})
    assert {r["code"]: r for r in hist}["RIE-ACX-07"]["probability"] == 2
    ov = ap.risk_matrix("ACSELX", items(), overrides={"RIE-ACX-01": {"probability": 3, "impact": 3, "reason": "r"}})
    assert {r["code"]: r for r in ov}["RIE-ACX-01"]["level"] == "Medio"


def test_maturity_traceability_and_opinion():
    mat = {m["key"]: m for m in ap.maturity("ACSELX", ap.criteria(), items())}
    assert mat["DSS05"]["suggested"] == 3 and mat["A.8.24"]["suggested"] == 2
    tr = ap.traceability("ACSELX", items())
    assert len(tr) == 7 and {t["state"] for t in tr} == {"CONFORME", "HALLAZGO DE AUDITORÍA"}
    ov = ap.overview(ap.criteria(), items())
    key, label = ap.opinion(ov, ap.risk_matrix("ACSELX", items()))
    assert key == "DESFAVORABLE"            # 4+ riesgos críticos materializados
    text = ap.opinion_text("Acsel/x", ov, ap.risk_matrix("ACSELX", items()), ap.block_summary(ap.criteria(), items()))
    assert "Acsel/x" in text and "15 de 30" in text


def test_directed_survey_rows_and_data_checks():
    crit = ap.criteria()
    areas = {a["area"]: a["questions"] for a in ap.areas_in(crit)}
    assert sum(areas.values()) == 30 and areas["INFRAESTRUCTURA"] == 5
    rows = ap.survey_rows(crit, "INFRAESTRUCTURA")
    assert rows[0]["data_label"].startswith("Frecuencia") and "≤ 15" in rows[0]["target"]
    bcp01 = next(c for c in crit if c["code"] == "BCP01")
    assert ap.data_verdict(bcp01, 30, ap.DEFAULT_PARAMS) == "NO"
    assert ap.inconsistency(bcp01, {"control": "SI", "dato": 30}, ap.DEFAULT_PARAMS)
    assert ap.inconsistency(bcp01, {"control": "SI", "dato": 10}, ap.DEFAULT_PARAMS) is None
    bcp03 = next(c for c in crit if c["code"] == "BCP03")
    assert ap.data_verdict(bcp03, "2026-01-10", ap.DEFAULT_PARAMS, today=date(2026, 11, 3)) == "NO"
    assert ap.data_verdict(bcp03, "2026-08-10", ap.DEFAULT_PARAMS, today=date(2026, 11, 3)) == "SI"
    assert ap.data_verdict(bcp03, "2026-08-10", {**ap.DEFAULT_PARAMS, "failover_months": 2}, today=date(2026, 11, 3)) == "NO"


def test_parse_survey_answer():
    crit = {c["code"]: c for c in ap.criteria()}
    assert ap.parse_survey_answer(crit["SEG01"], {"control": "Sí", "documental": "Sí", "evidencia": "Actualizado"}) == \
        {"control": "SI", "documental": "SI", "evidencia": "ACTUALIZADO"}
    assert ap.parse_survey_answer(crit["SEG04"], {"control": "No"}) == {"control": "NO", "documental": "NO", "evidencia": "INEXISTENTE"}
    assert ap.parse_survey_answer(crit["BCP01"], {"control": "si", "dato": "10,5"})["dato"] == 10.5
    assert ap.parse_survey_answer(crit["SEG01"], {}) is None


def test_norms_citation():
    text = norms.cite(["ISO-A.5.18", "COBIT-DSS05.04", "SUDEASEG-TI"])
    assert "ISO/IEC 27001:2022" in text and "COBIT 2019: DSS05.04" in text and "por validar" in text


def test_survey_roundtrip_is_signed_and_area_scoped():
    import io
    import pytest
    from openpyxl import load_workbook
    from app.modules.engagement import app_survey as sv
    crit = ap.criteria()
    data = sv.build({"id": "a1", "code": "S-SC-001-2026-A1"}, {"name": "Acsel/x"}, "INFRAESTRUCTURA", crit, [], ap.DEFAULT_PARAMS,
                    b"k" * 32, "jefe")
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Encuesta"]
    ws.cell(5, 4).value, ws.cell(6, 4).value, ws.cell(7, 4).value = "Ana Pérez", "Gerente de Infraestructura", "02/11/2026"
    ws.cell(sv.FIRST_ROW, 8).value, ws.cell(sv.FIRST_ROW, 9).value = "Sí", 10          # BCP01
    ws.cell(sv.FIRST_ROW, 10).value, ws.cell(sv.FIRST_ROW, 11).value = "Sí", "Actualizado"
    ws.cell(sv.FIRST_ROW + 2, 8).value = "No"                                          # BCP03 sin comentario
    buf = io.BytesIO(); wb.save(buf)
    out = sv.parse(buf.getvalue(), b"k" * 32, "a1", crit)
    assert out["area"] == "INFRAESTRUCTURA" and out["respondent"]["name"] == "Ana Pérez"
    assert out["answers"]["BCP01"] == {"control": "SI", "documental": "SI", "evidencia": "ACTUALIZADO", "dato": 10}
    assert any("BCP03" in p for p in out["problems"])
    with pytest.raises(sv.SurveyError):
        sv.parse(buf.getvalue(), b"x" * 32, "a1", crit)       # otra clave: firma inválida
    with pytest.raises(sv.SurveyError):
        sv.parse(buf.getvalue(), b"k" * 32, "otra", crit)     # otra auditoría
