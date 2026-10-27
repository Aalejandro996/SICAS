"""Cédulas tipo cuestionario: misma metodología que el Excel «Atributos Auditorias» (hoja LOPCYMAT)."""
from app.modules.engagement import scoring

# Bloque, peso y respuestas del ejemplo del Excel (Sí = CUMPLE, No = NO_CUMPLE).
LOPCYMAT = [
    ("1", 0.20, ["CUMPLE", "NO_CUMPLE", "CUMPLE"]),
    ("2", 0.15, ["CUMPLE", "CUMPLE", "NO_CUMPLE"]),
    ("3", 0.25, ["NO_CUMPLE", "CUMPLE", "CUMPLE", "CUMPLE", "CUMPLE"]),
    ("4", 0.20, ["NO_CUMPLE", "CUMPLE", "NO_CUMPLE", "NO_CUMPLE"]),
    ("5", 0.20, ["NO_CUMPLE", "CUMPLE", "CUMPLE", "NO_CUMPLE", "CUMPLE"]),
]


def build(spec, weighted=True):
    criteria, items = [], []
    for block, weight, answers in spec:
        for n, answer in enumerate(answers, 1):
            code = f"LOP-{block}.{n}"
            criteria.append({"code": code, "source_id": code, "text": code, "evaluation_mode": "FINANCIAL_CATALOG",
                             "template_code": "AUD_LOPCYMAT", "block": block, "block_title": f"Bloque {block}",
                             "block_weight": weight if weighted else None})
            if answer:
                items.append({"ref": code, "results": {code: answer},
                              "observation": "reseña" if answer in scoring.NEGATIVE_ANSWERS else None})
    return criteria, items


def test_excel_example_index_risk_and_critical_block():
    criteria, items = build(LOPCYMAT)
    q = scoring.questionnaire_summary(criteria, items)
    assert [b["compliance"] for b in q["blocks"]] == [66.67, 66.67, 80.0, 25.0, 60.0]
    assert q["index"] == 60.33                     # Excel: 0,6033
    assert q["risk"] == "MEDIO"
    assert q["critical"] == ["Bloque 4"]           # Excel: «IV. ... No cumple el promedio Requerido»
    assert scoring.worksheet_summary(criteria, items).auto == 60.33


def test_partial_counts_half_and_not_applicable_is_excluded():
    criteria, items = build([("1", 1.0, ["PARCIAL", "NO_APLICA", "CUMPLE"])])
    q = scoring.questionnaire_summary(criteria, items)
    assert q["blocks"][0]["compliance"] == 75.0 and q["risk"] == "MEDIO" and q["pending"] == 0


def test_pending_block_is_not_critical_yet():
    criteria, items = build([("1", 0.5, ["NO_CUMPLE", None]), ("2", 0.5, [None, None])])
    q = scoring.questionnaire_summary(criteria, items)
    assert q["critical"] == [] and q["pending"] == 3


def test_block_without_answers_counts_zero_like_the_excel():
    # Excel: SI.ERROR(PROMEDIO(...); 0) -> un bloque todo N/A aporta 0 y su peso no se reparte.
    criteria, items = build([("1", 0.5, ["CUMPLE", "CUMPLE"]), ("2", 0.5, ["NO_APLICA", "NO_APLICA"])])
    q = scoring.questionnaire_summary(criteria, items)
    assert q["blocks"][1]["compliance"] is None and q["blocks"][1]["contribution"] == 0.0
    assert q["index"] == 50.0 and q["risk"] == "ALTO"


def test_critical_counts_not_applicable_as_questions_like_the_excel():
    # Excel: puntos < (preguntas / 2). 1 Sí + 3 N/A = 1 punto < 4/2 -> crítico, aunque su promedio sea 100 %.
    criteria, items = build([("1", 1.0, ["CUMPLE", "NO_APLICA", "NO_APLICA", "NO_APLICA"])])
    q = scoring.questionnaire_summary(criteria, items)
    assert q["blocks"][0]["compliance"] == 100.0 and q["critical"] == ["Bloque 1"]


def test_index_label_follows_the_excel():
    assert scoring.index_label("SERV_SUC") == "Índice de Madurez (IMS)"
    assert scoring.index_label("LOPCYMAT") == "Índice de cumplimiento LOPCYMAT"


def test_unweighted_checklist_is_simple_average():
    criteria, items = build([("1", None, ["CUMPLE", "CUMPLE", "NO_CUMPLE", "CUMPLE"])], weighted=False)
    q = scoring.questionnaire_summary(criteria, items)
    assert q["index"] == 75.0 and q["risk"] == "MEDIO"
    assert scoring.questionnaire_risk(80) == "BAJO" and scoring.questionnaire_risk(59.99) == "ALTO"


def test_indicators_include_blocks_for_the_report():
    criteria, items = build(LOPCYMAT)
    ind = scoring.evaluation_indicators([{"id": "w", "title": "LOPCYMAT", "kind": "LOPCYMAT", "criteria": criteria, "items": items}],
                                        {"final": 60.33, "rating": "ACEPTABLE"})
    sheet = ind["worksheets"][0]
    assert sheet["risk"] == "MEDIO" and len(sheet["blocks"]) == 5
    assert {i["key"]: i["value"] for i in sheet["indicators"]}["critical"] == 1


def test_report_pdf_renders_questionnaire_blocks():
    from tests.unit.test_engagement_report import sample_body
    from app.modules.engagement.report_builder import build_pdf
    criteria, items = build(LOPCYMAT)
    body = sample_body()
    body["indicators"] = scoring.evaluation_indicators(
        [{"id": "w", "title": "Cuestionario LOPCYMAT — General", "kind": "LOPCYMAT", "criteria": criteria, "items": items}],
        {"final": 60.33, "rating": "ACEPTABLE"})
    assert build_pdf(body, {"status": "DRAFT"}).startswith(b"%PDF")
