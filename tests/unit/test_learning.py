"""Retroalimentación del motor: historial, sugerencias y propuestas (nunca se activan solas)."""
from app.modules.engagement import learning as ln


def test_pattern_keys():
    assert ln.pattern_key("ws1:accesos") == "sudeaseg:accesos"
    assert ln.pattern_key("sis:respaldos") == "sis:respaldos"
    assert ln.pattern_key("ti_suc:abc:ciber") == "ti_suc:ciber"
    assert ln.pattern_key(None, ["SEG04"]) == "ctrl:SEG04"
    assert ln.pattern_key(None, ["A", "B"]) is None


def test_history_adjustments_up_and_down():
    rows = ([{"control": "SEG04", "conforme": False, "audit_code": f"A{i}", "app": "Acsel/x", "closed_at": f"2026-0{i}-01"} for i in range(1, 4)]
            + [{"control": "REG02", "conforme": True, "audit_code": f"B{i}", "app": "Acsel/x", "closed_at": f"2026-0{i}-01"} for i in range(1, 4)]
            + [{"control": "BCP01", "conforme": False, "audit_code": "C1", "closed_at": "2026-01-01"},
               {"control": "BCP01", "conforme": True, "audit_code": "C2", "closed_at": "2026-02-01"}])
    h = ln.history_adjustments(rows)
    assert h["SEG04"]["delta"] == 1 and "3 de sus últimas 3" in h["SEG04"]["reason"]
    assert h["REG02"]["delta"] == -1
    assert "BCP01" not in h                      # un solo fallo: sin evidencia suficiente


def test_suggestions_rank_similar_approved_findings():
    target = {"id": "t", "title": "Ausencia de control de gestión de accesos (SEG04)", "condition": "anulación de recibos sin segregación",
              "rule_key": "sis:accesos"}
    approved = [
        {"id": "1", "audit_code": "X", "title": "Ausencia de control de gestión de accesos", "condition": "usuarios con anulación y emisión",
         "cause": "No hay matriz de roles", "recommendation": "Separar perfiles", "rule_key": "sis:accesos"},
        {"id": "2", "audit_code": "Y", "title": "Respaldos sin prueba", "condition": "no se restaura", "cause": "c", "recommendation": "r",
         "rule_key": "sis:respaldos"},
    ]
    s = ln.suggestions(target, approved)
    assert s and s[0]["id"] == "1" and s[0]["same_topic"]
    assert all(x["id"] != "2" for x in s)


def test_proposals_need_repetition_and_are_not_duplicated():
    fb = [{"kind": "RISK_CHANGED", "pattern_key": "sis:accesos", "after": {"risk": "ALTO"}, "audit_code": f"A{i}"} for i in range(3)]
    fb += [{"kind": "OBS_DISCARDED", "pattern_key": "sudeaseg:cartelera", "audit_code": f"B{i}"} for i in range(3)]
    fb += [{"kind": "OBS_EDITED", "pattern_key": "sis:respaldos",
            "after": {"recommendation": f"Implementar respaldos diarios con prueba de restauración trimestral documentada {i}"},
            "audit_code": f"C{i}"} for i in range(3)]
    hist = [{"control": "SEG04", "conforme": False, "audit_code": f"D{i}", "template": "ACSELX"} for i in range(3)]
    props = ln.propose(fb, hist, {}, set())
    kinds = {(p["kind"], p["target"]) for p in props}
    assert ("RISK", "sis:accesos") in kinds and ("SUPPRESS", "sudeaseg:cartelera") in kinds
    assert ("RECOMMEND", "sis:respaldos") in kinds and ("WEIGHT", "ACSELX:SEG04") in kinds
    assert ln.propose(fb, hist, {}, set(kinds)) == []
    assert ln.propose(fb[:2], [], {}, set()) == []            # dos repeticiones no bastan


def test_apply_only_approved_rules():
    draft = {"rule_key": "sis:accesos", "risk": "MEDIO", "recommendation": "a"}
    assert ln.apply_rules(draft, {}) == draft
    out = ln.apply_rules(draft, {("RISK", "sis:accesos"): {"risk": "ALTO"}, ("RECOMMEND", "sis:accesos"): {"recommendation": "b"}})
    assert out["risk"] == "ALTO" and out["recommendation"] == "b" and out["rules_applied"] == ["RISK", "RECOMMEND"]
    assert ln.apply_rules(draft, {("SUPPRESS", "sis:accesos"): {"suppress": True}}) is None
