"""Informe Ejecutivo e Informe de Documentación: períodos, reglas de situación, contenido y tope de 15 páginas."""
import unittest
from datetime import date

from app.modules.general_reports import content
from app.modules.general_reports.pdf import MAX_PAGES, build_pdf, page_count

CATALOG = [
    {"topic": "suscripcion", "label": "suscripción y emisión de pólizas", "keywords": ["poliza", "suscrip"], "sort_order": 1,
     "criteria": "Normas SUDEASEG de la relación contractual.", "cause": "c", "effect": "Sanciones de la SUDEASEG.", "recommendation": "Depurar expedientes."},
    {"topic": "siniestros", "label": "atención de siniestros", "keywords": ["siniestro", "indemniz"], "sort_order": 2,
     "criteria": "Plazos de pago de siniestros (SUDEASEG).", "cause": "c", "effect": "Reclamos de asegurados.", "recommendation": "Cumplir los plazos."},
    {"topic": "general", "label": "control interno", "keywords": [], "sort_order": 99,
     "criteria": "Normas de control interno.", "cause": "c", "effect": "Debilidad de control.", "recommendation": "Reforzar controles."},
]


def audit(i, unit, score, risks, phase="INFORME", long=False):
    text = "Detalle de la condición encontrada durante la revisión de la muestra. " * (10 if long else 1)
    return {"id": f"id-{i}", "code": f"A-SC-{i:03d}-2026-A1", "title": "Auditoría", "unit_name": unit, "unit_kind": "SUCURSAL",
            "audit_kind": "OPERATIVA", "phase": phase, "status": "IN_PROGRESS", "period_from": "2026-01-01", "period_to": "2026-06-30",
            "score": score, "rating": "ACEPTABLE", "limitations": 1, "closed_at": "2026-08-15",
            "observations": [{"title": f"Pólizas sin documentos {n}" if n % 2 else f"Siniestro pagado fuera de plazo {n}", "risk": r,
                              "condition": text, "criteria": "", "recommendation": text, "pac_status": "PENDIENTE"}
                             for n, r in enumerate(risks)]}


def body(audits):
    return content.build(audits=audits, catalog=CATALOG, company="Seguros Constitución", domain="FINANCIERA", title="Estado de sucursales",
                         code="IE-F-2026-001", author={"name": "Ana Pérez", "role": "Auditor"}, filters_text="cerradas",
                         today=date(2026, 10, 28), period_label="tercer trimestre de 2026")


STATE = {"status": "DRAFT", "body_sha256": "a" * 64, "auditor": None, "jefe": None, "acks": []}


class PeriodTests(unittest.TestCase):
    def test_quarter_semester_year(self):
        self.assertEqual(content.period_range("TRIMESTRE", 3, 2026), (date(2026, 7, 1), date(2026, 10, 1), "tercer trimestre de 2026"))
        self.assertEqual(content.period_range("TRIMESTRE", 4, 2026)[1], date(2027, 1, 1))
        self.assertEqual(content.period_range("SEMESTRE", 1, 2026)[:2], (date(2026, 1, 1), date(2026, 7, 1)))
        self.assertEqual(content.period_range("ANUAL", 1, 2026)[2], "año 2026")
        with self.assertRaises(ValueError):
            content.period_range("TRIMESTRE", 5, 2026)


class SituationTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(content.situation(90, {"ALTO": 3}), "CRITICA")
        self.assertEqual(content.situation(45, {}), "CRITICA")
        self.assertEqual(content.situation(90, {"ALTO": 1}), "ATENCION")
        self.assertEqual(content.situation(65, {}), "ATENCION")
        self.assertEqual(content.situation(90, {"MEDIO": 1}), "ACEPTABLE")
        self.assertEqual(content.situation(80, {}), "ACEPTABLE")
        self.assertEqual(content.situation(95, {}), "FAVORABLE")
        self.assertEqual(content.situation(None, {}), "SIN_CALIFICAR")
        self.assertEqual(content.situation(None, {"BAJO": 1}), "FAVORABLE")


class ContentTests(unittest.TestCase):
    def test_sections_units_and_topics(self):
        b = body([audit(1, "PORLAMAR", 40, ["ALTO", "ALTO", "MEDIO"]), audit(2, "PORLAMAR", 60, ["ALTO"]), audit(3, "CARACAS", 92, [])])
        for key in ("introduction", "scope", "objectives", "conclusion", "units", "audits", "topics"):
            self.assertTrue(b[key], key)
        self.assertIn("SUDEASEG", b["introduction"])
        self.assertIn("tercer trimestre de 2026", b["introduction"])
        self.assertEqual(b["kind"], "EJECUTIVO")
        first = next(a for a in b["audits"] if a["code"] == "A-SC-001-2026-A1")
        self.assertIn("cerrada el 15/08/2026", first["summary"])
        self.assertIn("2 de riesgo alto", first["summary"])
        self.assertEqual(set(first["observations"][0]), {"title", "risk", "pac_status", "topic"})   # breve: título y riesgo
        units = {u["unit"]: u for u in b["units"]}
        self.assertEqual(units["PORLAMAR"]["score"], 50.0)
        self.assertEqual(units["PORLAMAR"]["situation"], "CRITICA")        # 3 hallazgos altos
        self.assertEqual(units["CARACAS"]["situation"], "FAVORABLE")
        self.assertEqual(b["units"][0]["unit"], "PORLAMAR")                # lo más desfavorable primero
        topics = {t["topic"]: t for t in b["topics"]}
        self.assertEqual(set(topics), {"suscripcion", "siniestros"})
        self.assertEqual(b["kpis"]["by_risk"], {"ALTO": 3, "MEDIO": 1, "BAJO": 0})
        self.assertTrue(any("PORLAMAR" in c for c in b["conclusion"]))

    def test_no_findings(self):
        b = body([audit(1, "CARACAS", 95, [])])
        self.assertEqual(b["topics"], [])
        self.assertTrue(any("No se registran hallazgos" in c for c in b["conclusion"]))


def doc_audit(i, statuses):
    return {"id": f"d-{i}", "code": f"S-SC-{i:03d}-2026-A1", "title": "TI", "unit_name": f"Unidad {i}", "phase": "DOCUMENTACION",
            "period_from": "2026-01-01", "period_to": "2026-06-30",
            "letter": [{"ref": f"TI{n:03d}", "question": "¿Existe la política de respaldos aprobada?", "status": st, "note": "", "documents": 1 if st else 0}
                       for n, st in enumerate(statuses)]}


def doc_body(audits):
    return content.build_documentation(audits=audits, company="Seguros Constitución", title="Documentación", code="ID-S-2026-001",
                                       author={"name": "Ana Pérez", "role": "Auditor"}, filters_text="fase de documentación",
                                       today=date(2026, 10, 28))


class DocumentationTests(unittest.TestCase):
    def test_counts_and_conclusion(self):
        b = doc_body([doc_audit(1, ["ACTUALIZADA", "DESACTUALIZADA", "NO_ENTREGADA", "SIN_RESPUESTA", None])])
        self.assertEqual(b["kind"], "DOCUMENTACION")
        self.assertEqual((b["kpis"]["requested"], b["kpis"]["received"], b["kpis"]["rate"]), (5, 2, 40.0))
        self.assertEqual(b["audits"][0]["counts"]["PENDIENTE"], 1)
        self.assertTrue(any("Menos de la mitad" in c for c in b["conclusion"]))

    def test_pdf_within_15_pages(self):
        b = doc_body([doc_audit(i, ["ACTUALIZADA", "NO_ENTREGADA", "SIN_RESPUESTA"] * 15) for i in range(40)])
        self.assertLessEqual(page_count(b, STATE), MAX_PAGES)
        self.assertTrue(build_pdf(doc_body([doc_audit(1, ["ACTUALIZADA"])]), STATE).startswith(b"%PDF"))


class PdfTests(unittest.TestCase):
    def test_small_report(self):
        pdf = build_pdf(body([audit(1, "PORLAMAR", 40, ["ALTO", "MEDIO"])]), STATE)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_large_report_stays_within_15_pages(self):
        audits = [audit(i, f"SUCURSAL {i % 20}", 30 + i, ["ALTO", "MEDIO", "BAJO"] * 4, long=True) for i in range(60)]
        b = body(audits)
        self.assertLessEqual(page_count(b, STATE), MAX_PAGES)
        signed = {**STATE, "status": "APPROVED", "auditor": {"name": "Ana Pérez", "initials": "AP", "date": "28/10/2026"},
                  "jefe": {"name": "Luis Díaz", "date": "28/10/2026", "image": None},
                  "acks": [{"name": "Gerente", "role": "Gerencia", "date": "28/10/2026", "image": b"x"}]}
        self.assertLessEqual(page_count(b, signed), MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
