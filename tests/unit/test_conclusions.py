"""Motor de conclusiones, Informe Ejecutivo (tendencia, LC/FT/FPADM, planes vencidos), Informe de Documentación
(controles críticos y techo de Pruebas de campo), conclusión editable y cédula de prevención LC/FT/FPADM."""
import pathlib
import re
import unittest
from datetime import date

from app.modules.engagement import conclusions as cc
from app.modules.engagement.regulatory_rules import topic_for
from app.modules.general_reports import content
from app.modules.general_reports.api import keep_conclusion

ROOT = pathlib.Path(__file__).resolve().parents[2]
SQL = (ROOT / "sql" / "042_lcft_fpadm.sql").read_text(encoding="utf-8")
OVERALL = {"final": 62.0, "rating": "NECESITA_MEJORAS", "exceptions": 1}


def obs(topic, risk, label=None, cause="Falta un procedimiento formal."):
    return {"title": f"Hallazgo de {topic}", "risk": risk, "topic": topic, "topic_label": label or topic, "topic_cause": cause}


def catalog_from_sql():
    rows = re.findall(r"\('(lcft\w*)', '([^']*)', ARRAY\[(.*?)\]::text\[\]", SQL)
    return [{"topic": t, "label": l, "keywords": re.findall(r"'([^']*)'", kw), "sort_order": 30 + i}
            for i, (t, l, kw) in enumerate(rows)] + [{"topic": "general", "label": "control interno", "keywords": [], "sort_order": 99}]


class OpinionTests(unittest.TestCase):
    def test_opinion_follows_rating_scale_and_risks(self):
        self.assertEqual(cc.opinion("NO_SATISFACTORIA", {}), "DESFAVORABLE")
        self.assertEqual(cc.opinion("EXCELENTE", {"ALTO": 3}), "DESFAVORABLE")
        self.assertEqual(cc.opinion("ACEPTABLE", {}), "SALVEDADES")
        self.assertEqual(cc.opinion("EXCELENTE", {"ALTO": 1}), "SALVEDADES")
        self.assertEqual(cc.opinion("SATISFACTORIO", {"MEDIO": 2}), "OBSERVACIONES")
        self.assertEqual(cc.opinion("EXCELENTE", {}), "FAVORABLE")
        self.assertEqual(cc.opinion("SIN_CALIFICAR", {}), "SIN_CALIFICAR")

    def test_operativa_with_previous_audit_and_lcft(self):
        text = cc.audit_conclusion(
            preliminary=False, audit_kind="OPERATIVA", domain="FINANCIERA", modality="PRESENCIAL", unit="Sucursal Centro",
            overall=OVERALL, sheets=[{"title": "Suscripción — Auto", "kind": "SUSCRIPCION", "final": 55.0},
                                     {"title": "Reclamo — Auto", "kind": "RECLAMO", "final": 92.0}],
            questionnaires=[{"kind": "LCFT", "title": "Prevención LC/FT/FPADM", "index": 48.0, "risk": "ALTO",
                             "critical": ["III. Conozca a su cliente y debida diligencia"], "index_label": "Índice de cumplimiento LC/FT/FPADM"}],
            observations=[obs("lcft", "ALTO", "conozca a su cliente"), obs("lcft", "MEDIO", "conozca a su cliente"), obs("siniestros", "BAJO")],
            limitations=1, previous={"code": "C-SC-001-2025-A1", "closed_at": "2025-08-01", "score": 75.0, "topics": ["lcft"]})
        paragraphs = text.split("\n\n")
        self.assertIn("CON SALVEDADES", paragraphs[0])
        self.assertIn("«Suscripción — Auto» (55.0 %)", text)
        self.assertNotIn("Reclamo — Auto", text)                       # supera el 85 %: no es débil
        self.assertIn("Prevención LC/FT/FPADM", text)
        self.assertIn("atención prioritaria", text)
        self.assertIn("Causa común identificada en conozca a su cliente", text)
        self.assertIn("desmejoró 13.0 puntos", text)
        self.assertIn("Se repiten hallazgos en conozca a su cliente", text)
        self.assertIn("1 excepción(es)", text)
        self.assertIn("comenzando por las de riesgo alto", text)

    def test_systems_analysis_and_first_audit(self):
        text = cc.audit_conclusion(
            preliminary=True, audit_kind="SISTEMAS", domain="SISTEMAS", modality="REMOTA", unit="Gerencia de TI",
            overall={"final": 91.0, "rating": "SATISFACTORIO", "final_method": "PROMEDIO_FASES"}, sheets=[], questionnaires=[],
            observations=[], limitations=0, previous=None,
            systems={"phases": [{"phase": "LEVANTAMIENTO", "score": 94.0}, {"phase": "DOCUMENTACION", "score": 67.0}],
                     "requested": 10, "received": 6, "critical_domains": ["respaldo y recuperación de la información"]})
        self.assertIn("PRELIMINAR", text)
        self.assertIn("FAVORABLE", text)
        self.assertIn("Levantamiento de información 94.0 %", text)
        self.assertIn("documentación de 6 (60.0 %)", text)
        self.assertIn("respaldo y recuperación", text)
        self.assertIn("primera auditoría de Gerencia de TI", text)
        self.assertIn("promedio de las fases", text)

    def test_administrativa_process_wording(self):
        text = cc.audit_conclusion(preliminary=False, audit_kind="ADMINISTRATIVA", domain="FINANCIERA", modality="PRESENCIAL",
                                   unit="Finanzas", overall={"final": 95.0, "rating": "ACEPTABLE"},
                                   sheets=[{"title": "Gestión administrativa", "kind": "ADMIN", "final": 95.0}], questionnaires=[],
                                   observations=[], limitations=0, previous=None)
        self.assertIn("procesos revisados presentan controles", text)
        self.assertIn("sin observaciones", text)

    def test_annotate_topics_uses_rule_key_first(self):
        catalog = catalog_from_sql()
        out = cc.annotate_topics([{"title": "x", "rule_key": "w1:lcft_pep"}, {"title": "Sin reporte a la UNIF de operaciones inusuales"}], catalog)
        self.assertEqual(out[0]["topic"], "lcft_pep")
        self.assertEqual(out[1]["topic"], "lcft_reporte")
        self.assertTrue(cc.is_lcft_topic("lcft") and cc.is_lcft_topic("lcft_siar") and not cc.is_lcft_topic("pagos"))


class LcftCatalogTests(unittest.TestCase):
    def test_every_question_maps_to_its_block_topic(self):
        catalog = catalog_from_sql()
        expected = {"1": "lcft_siar", "2": "lcft_siar", "3": "lcft", "4": "lcft_pep", "5": "lcft_reporte", "6": "lcft_registros",
                    "7": "lcft_capacitacion", "8": "lcft_terceros"}
        rows = re.findall(r"\('AUD_LCFT', 'LCFT-(\d)\.\d', '([^']*)', NULL, '((?:[^']|'')*)'", SQL)
        self.assertEqual(len(rows), 26)
        for block, section, text in rows:
            self.assertEqual(topic_for(catalog, section, text.replace("''", "'"), "Prevención LC/FT/FPADM — General")["topic"], expected[block], text)

    def test_weights_add_up_and_norm_cited(self):
        weights = {b: float(w) for b, w in re.findall(r'"block": "(\d)".*?"block_weight": ([0-9.]+)', SQL)}
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertIn("SAA-01-0536-2024", SQL)
        self.assertEqual(len(re.findall(r"\('lcft\w*', '", SQL)), 7)


def audit(i, unit, score, risks, previous=None, lcft=None, due="2026-09-01"):
    return {"id": f"id-{i}", "code": f"A-{i}", "title": "Auditoría", "unit_name": unit, "unit_kind": "SUCURSAL", "audit_kind": "OPERATIVA",
            "phase": "INFORME", "status": "CLOSED", "period_from": "2026-01-01", "period_to": "2026-06-30", "score": score,
            "rating": "ACEPTABLE", "limitations": 0, "closed_at": "2026-08-15", "previous": previous, "lcft": lcft,
            "observations": [{"title": f"Hallazgo {n}", "risk": r, "topic": t, "topic_label": t, "pac_status": "PENDIENTE", "pac_due": due}
                             for n, (r, t) in enumerate(risks)]}


CAT = [{"topic": t, "label": t, "keywords": [], "sort_order": i, "criteria": "c", "cause": "c", "effect": "e", "recommendation": "r"}
       for i, t in enumerate(("lcft", "lcft_pep", "siniestros", "general"))]


class ExecutiveTests(unittest.TestCase):
    def build(self, audits, previous_period=None):
        return content.build(audits=audits, catalog=CAT, company="C", domain="FINANCIERA", title="T", code="IE-F-2026-001",
                             author={"name": "Ana Pérez", "role": "Auditor"}, filters_text="f", today=date(2026, 10, 28),
                             period_label="tercer trimestre de 2026", previous_period=previous_period)

    def test_trend_spread_recurrence_overdue_and_lcft(self):
        b = self.build([
            audit(1, "Caracas", 60.0, [("ALTO", "lcft"), ("MEDIO", "siniestros")],
                  previous={"code": "A-0", "closed_at": "2025-08-01", "score": 70.0, "topics": ["lcft"]},
                  lcft={"kind": "LCFT", "index": 45.0, "risk": "ALTO", "critical": ["IV. PEP"]}),
            audit(2, "Valencia", 90.0, [("BAJO", "siniestros")], previous=None, due="2026-12-01")],
            previous_period={"label": "segundo trimestre de 2026", "audits": 3, "avg_score": 80.0, "by_risk": {"ALTO": 0, "MEDIO": 1, "BAJO": 0}})
        text = " ".join(b["conclusion"])
        self.assertIn("Frente al segundo trimestre de 2026", text)
        self.assertIn("desmejoró 5.0 puntos", text)
        self.assertIn("pasaron de 0 a 1", text)
        self.assertIn("Se repiten en varias unidades: siniestros (Caracas y Valencia)", text)
        self.assertIn("se repiten temas de la auditoría anterior", text)
        self.assertIn("2 plan(es) de acción vencido(s)", text)              # el de Valencia vence en diciembre
        self.assertEqual(b["kpis"]["pac_overdue"], 2)
        self.assertEqual(b["lcft"]["audits"][0]["index"], 45.0)
        self.assertIn("SAA-01-0536-2024", b["lcft"]["text"])
        self.assertIn("Oficial de Cumplimiento", b["lcft"]["text"])
        first = b["audits"][0]["summary"]
        self.assertIn("Frente a la auditoría anterior (A-0)", first)
        self.assertIn("Prevención LC/FT/FPADM: índice 45.0 %", first)
        self.assertIn("2 vencido(s)", first)
        self.assertIn("primera auditoría de la unidad", b["audits"][1]["summary"])
        self.assertEqual(b["conclusion_auto"], b["conclusion"])
        self.assertFalse(b["conclusion_custom"])

    def test_previous_period(self):
        self.assertEqual(content.previous_period("TRIMESTRE", 1, 2026), ("TRIMESTRE", 4, 2025))
        self.assertEqual(content.previous_period("SEMESTRE", 2, 2026), ("SEMESTRE", 1, 2026))
        self.assertEqual(content.previous_period("ANUAL", 1, 2026), ("ANUAL", 1, 2025))


class DocumentationTests(unittest.TestCase):
    def test_critical_missing_and_ceiling(self):
        letter = [{"ref": "C1", "question": "Respaldos", "status": "NO_ENTREGADA", "domain": "respaldo y recuperación de la información", "critical": True},
                  {"ref": "C2", "question": "Cambios", "status": "ACTUALIZADA", "domain": "gestión de cambios", "critical": False},
                  {"ref": "C3", "question": "Accesos", "status": "SIN_RESPUESTA", "domain": "gestión de accesos e identidades", "critical": True},
                  {"ref": "C4", "question": "Inventario", "status": "DESACTUALIZADA", "domain": "inventario", "critical": False}]
        b = content.build_documentation(audits=[{"id": "1", "code": "S-1", "title": "t", "unit_name": "Gerencia de TI", "phase": "DOCUMENTACION",
                                                 "period_from": "", "period_to": "", "letter": letter}],
                                        company="C", title="T", code="ID-S-2026-001", author={"name": "A", "role": "Auditor"},
                                        filters_text="f", today=date(2026, 10, 28))
        row = b["audits"][0]
        self.assertEqual(row["ceiling"], 50.0)
        self.assertEqual([c["ref"] for c in row["critical_missing"]], ["C1", "C3"])
        self.assertIn("no podrá superar 50.0 %", row["summary"])
        text = " ".join(b["conclusion"])
        self.assertIn("controles críticos", text)
        self.assertIn("Gerencia de TI (2)", text)
        self.assertIn("techo más bajo es Gerencia de TI (50.0 %)", text)


class EditableConclusionTests(unittest.TestCase):
    def test_custom_conclusion_survives_regeneration(self):
        old = {"conclusion": ["Texto del auditor."], "conclusion_auto": ["A"], "conclusion_custom": True}
        same = keep_conclusion({"conclusion": ["A"], "conclusion_auto": ["A"], "conclusion_custom": False}, old)
        self.assertEqual(same["conclusion"], ["Texto del auditor."])
        self.assertTrue(same["conclusion_custom"]); self.assertFalse(same["conclusion_changed"])
        changed = keep_conclusion({"conclusion": ["B"], "conclusion_auto": ["B"], "conclusion_custom": False}, old)
        self.assertTrue(changed["conclusion_changed"])
        self.assertEqual(changed["conclusion_auto"], ["B"])

    def test_automatic_conclusion_is_replaced(self):
        new = {"conclusion": ["B"], "conclusion_auto": ["B"], "conclusion_custom": False}
        self.assertIs(keep_conclusion(new, {"conclusion": ["A"], "conclusion_auto": ["A"], "conclusion_custom": False}), new)
        self.assertIsNone(keep_conclusion(None, {"conclusion_custom": True}))


if __name__ == "__main__":
    unittest.main()
