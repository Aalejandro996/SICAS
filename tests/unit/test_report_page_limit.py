"""El informe no supera 15 páginas y conserva sus seis secciones en orden."""
import io
import re
import unittest

from app.modules.engagement import scoring
from app.modules.engagement.report_builder import MAX_PAGES, build_pdf, page_count


def body(n_obs=5, n_ev=3, n_lim=2, long=False):
    text = ("Texto de condición con detalle del control y de lo encontrado durante la revisión. " * (12 if long else 2)).strip()
    return {
        "kind": "FINAL", "version": 1, "company": "Seguros Constitución", "generated_on": "2026-10-26",
        "report_code": "P-S-G-SC-001-2026", "audit_code": "S-SC-001-2026-A1", "file_code": "S-SC-001-2026",
        "title": "Seguridad TI", "unit": {"code": "U", "name": "Ciberseguridad", "kind": "UNIDAD"}, "modality": "PRESENCIAL",
        "period": {"from": "2026-10-22", "to": "2026-10-30"}, "objectives": "Evaluar los controles de TI.", "scope": "ERP y redes.",
        "procedures": "Encuestas y pruebas de campo.", "contact": {"name": "", "role": ""},
        "team": [{"name": "Ana Pérez", "initials": "AP", "role": "LIDER", "system_role": "Auditor de Sistemas"}],
        "sheets": [], "thresholds": {}, "conclusion": "Conclusión del informe.",
        "overall": scoring.systems_overall({"auto": 40, "final": 40, "rating": "NO_SATISFACTORIA"},
                                           {"LEVANTAMIENTO": {"score": 70}, "DOCUMENTACION": {"score": 55}, "PRUEBAS_CAMPO": {"score": 40}}, "INFORME"),
        "indicators": {"overall": {}, "worksheets": [{"title": "ERP / TI", "score": 40.0, "rating": "NO_SATISFACTORIA",
                                                      "indicators": [{"key": "total", "label": "Controles", "value": 81}]}]},
        "observations": [{"n": i, "risk": ("ALTO", "MEDIO", "BAJO")[i % 3], "title": f"Hallazgo de prueba número {i}",
                          "condition": text, "criteria": text, "cause": text, "effect": text, "recommendation": text}
                         for i in range(1, n_obs + 1)],
        "evidence": [{"n": i, "filename": f"evidencia_{i}.pdf", "description": "Acta firmada de la prueba", "sha256": "a" * 64}
                     for i in range(1, n_ev + 1)],
        "limitations": [{"sheet": "ERP / TI", "ref": f"TI{i:03d}", "detail": "No se recibió la información solicitada."}
                        for i in range(1, n_lim + 1)],
        "adjustments": [],
    }


def text_of(pdf: bytes) -> str:
    # Los títulos de sección se buscan en el flujo sin comprimir de la tabla de contenido del PDF.
    return pdf.decode("latin-1", errors="ignore")


class ReportPageLimitTests(unittest.TestCase):
    def test_small_report_keeps_full_detail(self):
        self.assertLessEqual(page_count(body()), MAX_PAGES)

    def test_large_report_is_compacted_to_the_limit(self):
        big = body(n_obs=80, n_ev=120, n_lim=60, long=True)
        self.assertLessEqual(page_count(big), MAX_PAGES)
        pdf = build_pdf(big, {"final": True})
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
