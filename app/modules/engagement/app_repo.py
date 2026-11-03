"""Acceso a datos de la auditoría de aplicativos y de la retroalimentación del motor."""
from __future__ import annotations

import json
import uuid

from .repositories import db, q, q1, x

APP_SQL = ("SELECT u.id AS unit_id, u.code, u.name, u.active, u.responsible_name, u.responsible_role, p.vendor, p.product, p.version, "
           "p.category, p.model, p.db_engine, p.hosting, p.criticality, p.owner_unit_id, ou.name AS owner_unit_name, p.custodian, "
           "p.users_count, p.modules, p.interfaces, p.template_code, p.params, p.updated_at, "
           "(SELECT count(*) FROM engagement.files f JOIN engagement.audits a ON a.file_id = f.id "
           " WHERE f.unit_id = u.id AND a.status <> 'ANULADA') AS audits "
           "FROM engagement.units u JOIN engagement.applications p ON p.unit_id = u.id "
           "LEFT JOIN engagement.units ou ON ou.id = p.owner_unit_id ")
PROFILE_FIELDS = ("vendor", "product", "version", "category", "model", "db_engine", "hosting", "criticality", "owner_unit_id",
                  "custodian", "users_count", "modules", "interfaces", "template_code")


def applications(active_only=False):
    return q(APP_SQL + ("WHERE u.active " if active_only else "") + "ORDER BY u.name")


def application(unit_id):
    return q1(APP_SQL + "WHERE u.id = :u", u=int(unit_id))


def application_for_audit(audit_id):
    return q1(APP_SQL + "WHERE u.id = (SELECT f.unit_id FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id "
              "WHERE a.id = CAST(:a AS uuid))", a=str(audit_id))


def create_application(code, name, profile, params, user, responsible_name=None, responsible_role=None):
    r = q1("INSERT INTO engagement.units (code, name, kind, audit_domain, responsible_name, responsible_role) "
           "VALUES (:c, :n, 'APLICATIVO', 'SISTEMAS', :rn, :rr) RETURNING id", c=code, n=name, rn=responsible_name, rr=responsible_role)
    cols = ", ".join(PROFILE_FIELDS)
    vals = ", ".join(f":{k}" for k in PROFILE_FIELDS)
    x(f"INSERT INTO engagement.applications (unit_id, {cols}, params, updated_by) VALUES (:u, {vals}, CAST(:p AS jsonb), CAST(:by AS uuid))",
      u=r["id"], p=json.dumps(params), by=user, **{k: profile.get(k) for k in PROFILE_FIELDS})
    db.session.commit()
    return r["id"]


def update_application(unit_id, name, profile, params, user, responsible_name=None, responsible_role=None, active=True):
    x("UPDATE engagement.units SET name = :n, responsible_name = :rn, responsible_role = :rr, active = :ac WHERE id = :u AND kind = 'APLICATIVO'",
      n=name, rn=responsible_name, rr=responsible_role, ac=bool(active), u=int(unit_id))
    sets = ", ".join(f"{k} = :{k}" for k in PROFILE_FIELDS)
    x(f"UPDATE engagement.applications SET {sets}, params = CAST(:p AS jsonb), updated_by = CAST(:by AS uuid), updated_at = now() "
      "WHERE unit_id = :u", u=int(unit_id), p=json.dumps(params), by=user, **{k: profile.get(k) for k in PROFILE_FIELDS})
    db.session.commit()


# ------------------------------------------------------------------ pruebas, riesgos, madurez y encuestas
def tests(audit_id):
    return {r["code"]: r for r in q("SELECT t.code, t.result, t.detail, t.query_used, t.evidence_id::text, t.updated_at, "
                                     "u.full_name AS updated_by_name FROM engagement.app_tests t LEFT JOIN iam.users u ON u.id = t.updated_by "
                                     "WHERE t.audit_id = CAST(:a AS uuid)", a=str(audit_id))}


def save_test(audit_id, code, result, detail, query_used, evidence_id, user):
    x("INSERT INTO engagement.app_tests (audit_id, code, result, detail, query_used, evidence_id, updated_by) "
      "VALUES (CAST(:a AS uuid), :c, :r, :d, :q, CAST(:e AS uuid), CAST(:u AS uuid)) ON CONFLICT (audit_id, code) DO UPDATE SET "
      "result = EXCLUDED.result, detail = EXCLUDED.detail, query_used = EXCLUDED.query_used, evidence_id = EXCLUDED.evidence_id, "
      "updated_by = EXCLUDED.updated_by, updated_at = now()",
      a=str(audit_id), c=code, r=result, d=detail, q=query_used, e=evidence_id, u=user)


def risk_overrides(audit_id):
    return {r["risk_code"]: r for r in q("SELECT o.risk_code, o.probability, o.impact, o.reason, o.updated_at, u.full_name AS by_name "
                                          "FROM engagement.app_risk_overrides o LEFT JOIN iam.users u ON u.id = o.updated_by "
                                          "WHERE o.audit_id = CAST(:a AS uuid)", a=str(audit_id))}


def save_risk_override(audit_id, code, probability, impact, reason, user):
    if probability is None:
        x("DELETE FROM engagement.app_risk_overrides WHERE audit_id = CAST(:a AS uuid) AND risk_code = :c", a=str(audit_id), c=code)
        return
    x("INSERT INTO engagement.app_risk_overrides (audit_id, risk_code, probability, impact, reason, updated_by) VALUES "
      "(CAST(:a AS uuid), :c, :p, :i, :r, CAST(:u AS uuid)) ON CONFLICT (audit_id, risk_code) DO UPDATE SET probability = EXCLUDED.probability, "
      "impact = EXCLUDED.impact, reason = EXCLUDED.reason, updated_by = EXCLUDED.updated_by, updated_at = now()",
      a=str(audit_id), c=code, p=probability, i=impact, r=reason, u=user)


def maturity_overrides(audit_id):
    return {r["domain_key"]: r for r in q("SELECT m.domain_key, m.level, m.note, m.updated_at, u.full_name AS by_name "
                                           "FROM engagement.app_maturity m LEFT JOIN iam.users u ON u.id = m.updated_by "
                                           "WHERE m.audit_id = CAST(:a AS uuid)", a=str(audit_id))}


def save_maturity(audit_id, key, level, note, user):
    if level is None:
        x("DELETE FROM engagement.app_maturity WHERE audit_id = CAST(:a AS uuid) AND domain_key = :k", a=str(audit_id), k=key)
        return
    x("INSERT INTO engagement.app_maturity (audit_id, domain_key, level, note, updated_by) VALUES (CAST(:a AS uuid), :k, :l, :n, CAST(:u AS uuid)) "
      "ON CONFLICT (audit_id, domain_key) DO UPDATE SET level = EXCLUDED.level, note = EXCLUDED.note, updated_by = EXCLUDED.updated_by, updated_at = now()",
      a=str(audit_id), k=key, l=level, n=note, u=user)


def surveys(audit_id):
    return q("SELECT s.id::text, s.area, s.respondent_name, s.respondent_role, s.answered_on, s.filename, s.sha256, s.rows_applied, "
             "s.evidence_id::text, s.imported_at, u.full_name AS imported_by_name FROM engagement.app_surveys s "
             "LEFT JOIN iam.users u ON u.id = s.imported_by WHERE s.audit_id = CAST(:a AS uuid) ORDER BY s.imported_at DESC", a=str(audit_id))


def add_survey(audit_id, area, respondent, filename, sha, rows, evidence_id, user):
    x("INSERT INTO engagement.app_surveys (id, audit_id, area, respondent_name, respondent_role, answered_on, filename, sha256, rows_applied, "
      "evidence_id, imported_by) VALUES (CAST(:i AS uuid), CAST(:a AS uuid), :ar, :rn, :rr, :d, :f, :s, :n, CAST(:e AS uuid), CAST(:u AS uuid))",
      i=str(uuid.uuid4()), a=str(audit_id), ar=area, rn=respondent.get("name"), rr=respondent.get("role"), d=respondent.get("date"),
      f=filename, s=sha, n=rows, e=evidence_id, u=user)


def control_history(exclude_audit=None, apps_only=False):
    """Resultado de cada control o criterio en auditorías CERRADAS (ajuste de probabilidad y propuestas de peso).

    Plantilla: la del aplicativo (ACSELX…), «SISTEMAS/ERP_TI» en las de Sistemas por unidad y «TIPO/LÍNEA» en las
    cédulas de las demás auditorías (Operativa, Financiera, Administrativa, Especial). La Evaluación TI no cuenta.
    """
    from . import app_audit as ap
    from .regulatory_rules import ANSWERED, FAIL, _answer
    x_ = str(exclude_audit or uuid.UUID(int=0))
    rows = q("SELECT a.id::text AS audit_id, a.code AS audit_code, a.pac_sent_at AS closed_at, a.audit_kind, u.name AS app, "
             "CASE WHEN a.audit_kind = 'APLICATIVO' THEN COALESCE(p.template_code, 'ACSELX') ELSE 'SISTEMAS/' || w.line END AS template, "
             "i.ref AS control, i.results "
             "FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id JOIN engagement.units u ON u.id = f.unit_id "
             "LEFT JOIN engagement.applications p ON p.unit_id = u.id "
             "JOIN engagement.worksheets w ON w.audit_id = a.id AND w.kind = 'SISTEMAS' JOIN engagement.items i ON i.worksheet_id = w.id "
             "WHERE a.status = 'CLOSED' AND a.id <> CAST(:x AS uuid)" + (" AND a.audit_kind = 'APLICATIVO'" if apps_only else ""), x=x_)
    out = []
    for r in rows:
        res = (r.get("results") or {}).get(r["control"])
        if not isinstance(res, dict) or ap.control_points(res) is None:
            continue
        out.append({"control": r["control"], "conforme": ap.is_conforme(res), "audit_code": r["audit_code"],
                    "app": r["app"] if r["audit_kind"] == "APLICATIVO" else None, "closed_at": r["closed_at"], "template": r["template"]})
    if apps_only:
        return out
    sheets = q("SELECT w.id::text AS id, w.kind, w.line, w.criteria, a.code AS audit_code, a.pac_sent_at AS closed_at "
               "FROM engagement.worksheets w JOIN engagement.audits a ON a.id = w.audit_id "
               "WHERE a.status = 'CLOSED' AND a.id <> CAST(:x AS uuid) AND w.kind NOT IN ('SISTEMAS', 'TI_SUC')", x=x_)
    items = {}
    if sheets:
        for it in q("SELECT worksheet_id::text AS w, results FROM engagement.items WHERE worksheet_id = ANY(CAST(:ids AS uuid[]))",
                    ids=[w["id"] for w in sheets]):
            items.setdefault(it["w"], []).append(it.get("results") or {})
    for w in sheets:
        for c in w.get("criteria") or []:
            answers = [_answer(res, c) for res in items.get(w["id"], [])]
            if not c.get("code") or c.get("evaluation_mode") == "TI_SUC" or not any(v in ANSWERED for v in answers):
                continue
            out.append({"control": c["code"], "conforme": not any(v in FAIL for v in answers), "audit_code": w["audit_code"],
                        "app": None, "closed_at": w["closed_at"], "template": f"{w['kind']}/{w['line']}"})
    return out


def pattern_history(same_unit_as=None):
    """Hallazgos vigentes (ni descartados ni reemplazados) de auditorías CERRADAS, con su patrón, para el historial.

    same_unit_as: id de una auditoría; limita a las otras auditorías cerradas de su misma unidad.
    """
    from .learning import pattern_key
    rows = q("SELECT o.rule_key, a.code AS audit_code, a.pac_sent_at AS closed_at, u.name AS unit, o.risk "
             "FROM engagement.observations o JOIN engagement.audits a ON a.id = o.audit_id "
             "JOIN engagement.files f ON f.id = a.file_id JOIN engagement.units u ON u.id = f.unit_id "
             "WHERE a.status = 'CLOSED' AND o.rule_key IS NOT NULL AND o.superseded_by IS NULL AND o.discarded_at IS NULL "
             "AND a.id <> CAST(:x AS uuid)" + (" AND f.unit_id = (SELECT f2.unit_id FROM engagement.audits a2 "
                                                 "JOIN engagement.files f2 ON f2.id = a2.file_id WHERE a2.id = CAST(:x AS uuid))"
                                                 if same_unit_as else ""),
             x=str(same_unit_as or uuid.UUID(int=0)))
    return [{**r, "pattern_key": pattern_key(r["rule_key"])} for r in rows if pattern_key(r["rule_key"])]


# ------------------------------------------------------------------ retroalimentación del motor
def add_feedback(kind, user, audit_id=None, observation_id=None, pattern_key=None, controls=None, before=None, after=None, reason=None):
    x("INSERT INTO engagement.engine_feedback (audit_id, observation_id, kind, pattern_key, controls, before, after, reason, user_id) "
      "VALUES (CAST(:a AS uuid), CAST(:o AS uuid), :k, :p, :c, CAST(:b AS jsonb), CAST(:af AS jsonb), :r, CAST(:u AS uuid))",
      a=None if audit_id is None else str(audit_id), o=None if observation_id is None else str(observation_id), k=kind, p=pattern_key,
      c=list(controls or []), b=json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
      af=json.dumps(after, ensure_ascii=False, default=str) if after is not None else None, r=reason, u=user)


def feedback(limit=2000):
    return q("SELECT e.id, e.kind, e.pattern_key, e.controls, e.before, e.after, e.reason, e.created_at, a.code AS audit_code, "
             "u.full_name AS user_name FROM engagement.engine_feedback e LEFT JOIN engagement.audits a ON a.id = e.audit_id "
             "LEFT JOIN iam.users u ON u.id = e.user_id ORDER BY e.created_at DESC LIMIT :n", n=int(limit))


def approved_observations(exclude_audit):
    """Hallazgos de auditorías con informe final aprobado o firmado (fuente de las redacciones sugeridas)."""
    return q("SELECT o.id::text, o.title, o.condition, o.cause, o.effect, o.recommendation, o.risk, o.rule_key, a.code AS audit_code "
             "FROM engagement.observations o JOIN engagement.audits a ON a.id = o.audit_id "
             "WHERE o.superseded_by IS NULL AND o.discarded_at IS NULL AND a.id <> CAST(:a AS uuid) AND a.status <> 'ANULADA' "
             "AND EXISTS (SELECT 1 FROM engagement.reports r WHERE r.audit_id = a.id AND r.kind = 'FINAL' AND r.status IN ('APPROVED', 'SIGNED')) "
             "ORDER BY o.created_at DESC LIMIT 1500", a=str(exclude_audit))


def mark_accepted(oid, user):
    x("UPDATE engagement.observations SET accepted_by = CAST(:u AS uuid), accepted_at = now() WHERE id = CAST(:i AS uuid)", u=user, i=str(oid))


def mark_discarded(oid, user, reason):
    x("UPDATE engagement.observations SET discarded_by = CAST(:u AS uuid), discarded_at = now(), discard_reason = :r, "
      "superseded_by = id, updated_at = now() WHERE id = CAST(:i AS uuid)", u=user, r=reason, i=str(oid))


def proposals(status=None):
    return q("SELECT p.id::text, p.kind, p.target, p.value, p.rationale, p.evidence, p.status, p.proposed_at, p.decided_at, "
             "p.decision_note, u.full_name AS decided_by_name FROM engagement.rule_proposals p LEFT JOIN iam.users u ON u.id = p.decided_by "
             + ("WHERE p.status = :s " if status else "") + "ORDER BY (p.status = 'PROPUESTA') DESC, p.proposed_at DESC LIMIT 300",
             **({"s": status} if status else {}))


def add_proposal(p):
    pid = str(uuid.uuid4())
    x("INSERT INTO engagement.rule_proposals (id, kind, target, value, rationale, evidence) VALUES (CAST(:i AS uuid), :k, :t, "
      "CAST(:v AS jsonb), :r, CAST(:e AS jsonb)) ON CONFLICT DO NOTHING",
      i=pid, k=p["kind"], t=p["target"], v=json.dumps(p["value"], ensure_ascii=False), r=p["rationale"],
      e=json.dumps(p.get("evidence") or [], ensure_ascii=False, default=str))
    return pid


def get_proposal(pid):
    return q1("SELECT id::text, kind, target, value, rationale, evidence, status FROM engagement.rule_proposals WHERE id = CAST(:i AS uuid)", i=str(pid))


def decide_proposal(pid, status, note, user):
    x("UPDATE engagement.rule_proposals SET status = :s, decision_note = :n, decided_by = CAST(:u AS uuid), decided_at = now() "
      "WHERE id = CAST(:i AS uuid) AND status = 'PROPUESTA'", s=status, n=note, u=user, i=str(pid))


def activate_rule(p, user):
    x("UPDATE engagement.engine_rules SET active = FALSE, retired_by = CAST(:u AS uuid), retired_at = now() "
      "WHERE kind = :k AND target = :t AND active", k=p["kind"], t=p["target"], u=user)
    rid = str(uuid.uuid4())
    x("INSERT INTO engagement.engine_rules (id, kind, target, value, proposal_id, approved_by) VALUES (CAST(:i AS uuid), :k, :t, "
      "CAST(:v AS jsonb), CAST(:p AS uuid), CAST(:u AS uuid))",
      i=rid, k=p["kind"], t=p["target"], v=json.dumps(p["value"], ensure_ascii=False), p=p["id"], u=user)
    return rid


def rules(active_only=True):
    return q("SELECT r.id::text, r.kind, r.target, r.value, r.active, r.approved_at, r.retired_at, r.proposal_id::text, "
             "u.full_name AS approved_by_name FROM engagement.engine_rules r LEFT JOIN iam.users u ON u.id = r.approved_by "
             + ("WHERE r.active " if active_only else "") + "ORDER BY r.approved_at DESC")


def retire_rule(rid, user):
    x("UPDATE engagement.engine_rules SET active = FALSE, retired_by = CAST(:u AS uuid), retired_at = now() WHERE id = CAST(:i AS uuid) AND active",
      u=user, i=str(rid))


def active_rules_map():
    """{(tipo, objetivo): valor} de las reglas aprobadas y vigentes (vacío si la tabla aún no existe)."""
    try:
        return {(r["kind"], r["target"]): r["value"] for r in rules(True)}
    except Exception:  # noqa: BLE001
        db.session.rollback()
        return {}


def open_targets():
    return {(r["kind"], r["target"]) for r in q("SELECT kind, target FROM engagement.rule_proposals WHERE status IN ('PROPUESTA', 'RECHAZADA') "
                                                 "UNION SELECT kind, target FROM engagement.engine_rules WHERE active")}


def norms():
    return q("SELECT n.code, n.source, n.reference, n.title, n.summary, n.status, n.updated_at, u.full_name AS updated_by_name "
             "FROM engagement.norms n LEFT JOIN iam.users u ON u.id = n.updated_by ORDER BY n.source, n.code")


def norms_map():
    try:
        return {r["code"]: r for r in norms()}
    except Exception:  # noqa: BLE001
        db.session.rollback()
        return {}


def update_norm(code, status, summary, user):
    x("UPDATE engagement.norms SET status = :s, summary = :m, updated_by = CAST(:u AS uuid), updated_at = now() WHERE code = :c",
      s=status, m=summary, u=user, c=code)
