"""Acceso a datos de los informes consolidados (Informe Ejecutivo e Informe de Documentación)."""
from __future__ import annotations

import json
import uuid

from app.modules.engagement import assemble as asm
from app.modules.engagement import repositories as repo
from app.modules.engagement import systems_docs
from app.modules.engagement.repositories import q, q1, x, db

REPORT_SQL = ("SELECT r.id::text, r.code, r.audit_domain, r.report_kind, r.period, r.needs_refresh, r.title, r.status, r.filters, r.audit_ids::text[] AS audit_ids, r.body, "
              "r.body_sha256, r.revision, r.created_by::text, r.created_at, r.updated_at, "
              "r.auditor_signed_by::text, r.auditor_signed_at, r.auditor_signed_sha256, r.auditor_signature_sha256, "
              "r.jefe_by::text, r.jefe_at, r.jefe_sha256, r.jefe_signature_sha256, "
              "cu.full_name AS created_by_name, ju.full_name AS jefe_name "
              "FROM engagement.general_reports r JOIN iam.users cu ON cu.id = r.created_by "
              "LEFT JOIN iam.users ju ON ju.id = r.jefe_by ")


class StaleState(Exception):
    pass


TEAM = "EXISTS (SELECT 1 FROM engagement.team t WHERE t.audit_id = a.id AND t.user_id = CAST(:me AS uuid))"


def _scope(kind, period):
    """Condición de elegibilidad: Ejecutivo = cerradas en el período (fecha de cierre); Documentación = en fase 2 de Sistemas."""
    if kind == "DOCUMENTACION":
        return ["a.status = 'IN_PROGRESS'", "a.phase = 'DOCUMENTACION'", "a.audit_domain = 'SISTEMAS'"], {}
    return (["a.status = 'CLOSED'", "a.pac_sent_at >= CAST(:p0 AS date)", "a.pac_sent_at < CAST(:p1 AS date)"],
            {"p0": str(period["from"]), "p1": str(period["until"])})


def candidates(domains, f, user, kind, period):
    """Auditorías propias del Auditor (es del equipo) que entran en el informe, con los filtros de la pantalla."""
    where, p = _scope(kind, period)
    where += ["a.status <> 'ANULADA'", TEAM]
    p["me"] = user
    if "ALL" not in domains:
        where.append("a.audit_domain = ANY(CAST(:d AS text[]))"); p["d"] = sorted(domains)
    if f.get("audit_kind"):
        where.append("a.audit_kind = :k"); p["k"] = f["audit_kind"]
    if f.get("unit_id"):
        where.append("u.id = :u"); p["u"] = int(f["unit_id"])
    if f.get("unit_kind"):
        where.append("u.kind = :uk"); p["uk"] = f["unit_kind"]
    if f.get("q"):
        where.append("(a.code ILIKE :qq OR u.name ILIKE :qq OR f.title ILIKE :qq)"); p["qq"] = f"%{f['q']}%"
    return q("SELECT a.id::text, a.code, a.audit_kind, a.audit_domain, a.phase, a.status, f.title, f.period_from, f.period_to, "
             "a.pac_sent_at AS closed_at, u.id AS unit_id, u.name AS unit_name, u.kind AS unit_kind "
             "FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id JOIN engagement.units u ON u.id = f.unit_id "
             "WHERE " + " AND ".join(where) + " ORDER BY u.name, a.code LIMIT 300", **p)


def units(domains, user):
    p, cond = {"me": user}, ""
    if "ALL" not in domains:
        cond = "AND a.audit_domain = ANY(CAST(:d AS text[])) "; p["d"] = sorted(domains)
    return q("SELECT DISTINCT u.id, u.name, u.kind FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id "
             "JOIN engagement.units u ON u.id = f.unit_id WHERE a.status <> 'ANULADA' AND " + TEAM + " "
             + cond + "ORDER BY u.name", **p)


def documentation_data(a):
    """Controles de la carta de documentación y lo obtenido (Informe de Documentación)."""
    docs = {}
    for ev in repo.evidence(a["id"]):
        if ev.get("item_id"):
            docs.setdefault(ev["item_id"], []).append(ev["id"])
    letter = []
    for ws in repo.worksheets_with_items(a["id"]):
        if ws["kind"] == "SISTEMAS":
            letter += systems_docs.letter_rows(ws["items"], ws["criteria"], docs)
    return {"id": a["id"], "code": a["code"], "title": a["title"], "unit_name": a["unit_name"], "phase": a["phase"],
            "period_from": a["period_from"], "period_to": a["period_to"], "letter": letter}


def audit_data(a, thresholds, overall_for):
    """Calificación, hallazgos vigentes y limitaciones de una auditoría (para el motor del informe)."""
    sheets = [ws for ws in repo.worksheets_with_items(a["id"]) if not asm.scoring.ti_branch.is_ti_criteria(ws["criteria"])]
    th = thresholds(a)
    pairs = asm.summarize_sheets(sheets, th)
    overall = overall_for(a, pairs, th)
    limitations = sum(1 for ws in sheets for it in ws["items"]
                      if it.get("info_exception") or "EXCEPCION" in (it.get("results") or {}).values())
    return {"id": a["id"], "code": a["code"], "title": a["title"], "unit_name": a["unit_name"], "unit_kind": a["unit_kind"],
            "audit_kind": a.get("audit_kind"), "audit_domain": a.get("audit_domain"), "phase": a["phase"], "status": a["status"],
            "period_from": a["period_from"], "period_to": a["period_to"], "score": overall.get("final"), "rating": overall.get("rating"),
            "limitations": limitations, "closed_at": a.get("pac_sent_at"),
            # La Evaluación TI de la sucursal es informativa (módulo del Jefe de Sistemas): sus hallazgos no entran.
            "observations": [o for o in repo.observations(a["id"]) if not str(o.get("rule_key") or "").startswith("ti_suc:")]}


def catalog(domain):
    if domain == "SISTEMAS":
        rows = repo.systems_rule_catalog()
        return [{**r, "topic": r["domain_key"]} for r in rows]
    return repo.regulatory_catalog()


def next_code(kind, domain, year):
    prefix = f"{'ID' if kind == 'DOCUMENTACION' else 'IE'}-{domain[0]}-{year}-"
    row = q1("SELECT count(*) AS n FROM engagement.general_reports WHERE code LIKE :p", p=prefix + "%")
    return f"{prefix}{int(row['n']) + 1:03d}"


def create(kind, period, domain, title, filters, audit_ids, body, sha, user, actor_role):
    rid = str(uuid.uuid4())
    x("INSERT INTO engagement.general_reports (id, code, report_kind, period, audit_domain, title, filters, audit_ids, body, body_sha256, created_by) "
      "VALUES (CAST(:i AS uuid), :c, :k, CAST(:pe AS jsonb), :d, :t, CAST(:f AS jsonb), CAST(:a AS uuid[]), CAST(:b AS jsonb), :h, CAST(:u AS uuid))",
      i=rid, c=body["code"], k=kind, pe=json.dumps(period, default=str) if period else None, d=domain, t=title,
      f=json.dumps(filters, default=str), a=audit_ids, b=json.dumps(body, default=str), h=sha, u=user)
    _event(rid, "GENERATED", None, "DRAFT", sha, user, actor_role)
    db.session.commit()
    return rid


def get(rid):
    return q1(REPORT_SQL + "WHERE r.id = CAST(:i AS uuid)", i=str(rid))


def search(user, domains_review, can_read_approved, creator):
    """Informes visibles: los propios (Auditor), los del dominio enviados al Jefe y los aprobados (Gerencia y Contralor)."""
    cond, p = [], {"u": user}
    if creator:
        cond.append("r.created_by = CAST(:u AS uuid)")
    if domains_review:
        # El Jefe ve los informes de su dominio que ya le fueron enviados (en revisión, devueltos o aprobados).
        cond.append("r.status <> 'DRAFT' AND r.audit_domain = ANY(CAST(:d AS text[]))")
        p["d"] = sorted(domains_review)
    if can_read_approved:
        cond.append("r.status = 'APPROVED'")
    if not cond:
        return []
    rows = q("SELECT r.id::text, r.code, r.audit_domain, r.report_kind, r.period, r.title, r.status, r.revision, cardinality(r.audit_ids) AS audits, "
             "r.created_at, r.updated_at, r.auditor_signed_at, r.jefe_at, cu.full_name AS created_by_name, r.created_by::text, "
             "(r.body->'kpis'->>'avg_score')::numeric AS avg_score, r.body->'kpis'->'by_situation' AS by_situation, "
             "(SELECT count(*) FROM engagement.general_report_acks k WHERE k.report_id = r.id) AS acks "
             "FROM engagement.general_reports r JOIN iam.users cu ON cu.id = r.created_by WHERE "
             + " OR ".join(f"({c})" for c in cond) + " ORDER BY r.updated_at DESC LIMIT 200", **p)
    return rows


def events(rid):
    return q("SELECT e.id, e.action, e.from_status, e.to_status, e.body_sha256, e.actor_role, e.comment, e.created_at, "
             "u.full_name AS actor_name FROM engagement.general_report_events e JOIN iam.users u ON u.id = e.actor_id "
             "WHERE e.report_id = CAST(:r AS uuid) ORDER BY e.id", r=str(rid))


def acks(rid):
    return q("SELECT k.user_id::text, k.role, k.note, k.created_at, k.body_sha256, k.signature_sha256, u.full_name AS name "
             "FROM engagement.general_report_acks k JOIN iam.users u ON u.id = k.user_id "
             "WHERE k.report_id = CAST(:r AS uuid) ORDER BY k.created_at", r=str(rid))


def _event(rid, action, before, after, sha, user, role, comment=None):
    x("INSERT INTO engagement.general_report_events (report_id, action, from_status, to_status, body_sha256, actor_id, actor_role, comment) "
      "VALUES (CAST(:r AS uuid), :a, :f, :t, :h, CAST(:u AS uuid), :ro, :c)",
      r=rid, a=action, f=before, t=after, h=sha, u=user, ro=role, c=comment)


def transition(rep, status, action, user, role, comment=None, **fields):
    """Cambio de estado condicionado al estado y contenido leídos (si cambiaron, no se aplica)."""
    sets = ["status = :st", "updated_at = now()"] + [f"{k} = " + ("now()" if v == "now" else f":{k}") for k, v in fields.items()]
    params = {k: v for k, v in fields.items() if v != "now"}
    row = x("UPDATE engagement.general_reports SET " + ", ".join(sets) +
            " WHERE id = CAST(:i AS uuid) AND status = :old AND body_sha256 = :sha RETURNING id",
            st=status, i=rep["id"], old=rep["status"], sha=rep["body_sha256"], **params).first()
    if row is None:
        db.session.rollback()
        raise StaleState("El informe cambió mientras se procesaba la acción; recargue e intente de nuevo")
    _event(rep["id"], action, rep["status"], status, rep["body_sha256"], user, role, comment)
    db.session.commit()


def replace_body(rep, body, sha, audit_ids, user, role):
    row = x("UPDATE engagement.general_reports SET body = CAST(:b AS jsonb), body_sha256 = :h, audit_ids = CAST(:a AS uuid[]), "
            "revision = revision + 1, needs_refresh = FALSE, updated_at = now() WHERE id = CAST(:i AS uuid) AND body_sha256 = :old AND status = :st RETURNING id",
            b=json.dumps(body, default=str), h=sha, a=audit_ids, i=rep["id"], old=rep["body_sha256"], st=rep["status"]).first()
    if row is None:
        db.session.rollback()
        raise StaleState("El informe cambió mientras se regeneraba; recargue e intente de nuevo")
    _event(rep["id"], "REGENERATED", rep["status"], rep["status"], sha, user, role)
    db.session.commit()


def acknowledge(rep, user, role, note, signature_sha256, role_label):
    row = x("INSERT INTO engagement.general_report_acks (report_id, user_id, role, body_sha256, signature_sha256, note) "
            "VALUES (CAST(:r AS uuid), CAST(:u AS uuid), :ro, :h, :s, :n) ON CONFLICT DO NOTHING RETURNING report_id",
            r=rep["id"], u=user, ro=role, h=rep["body_sha256"], s=signature_sha256, n=note).first()
    if row is not None:
        _event(rep["id"], "ACKNOWLEDGED", rep["status"], rep["status"], rep["body_sha256"], user, role_label, note)
    db.session.commit()
    return row is not None


def signature(user_id):
    """Firma escaneada vigente registrada en SICAS (la que se estampa al aprobar)."""
    return repo.active_signature(user_id)


def signature_by_sha(user_id, sha):
    if not user_id or not sha:
        return None
    r = q1("SELECT content FROM engagement.signature_assets WHERE user_id = CAST(:u AS uuid) AND sha256 = :s LIMIT 1", u=user_id, s=sha)
    return bytes(r["content"]) if r else None


def refresh(rep, body, sha, audit_ids, user, role):
    """Actualiza con la data vigente un informe anterior al Informe Ejecutivo que sí cumple: vuelve a borrador."""
    x("UPDATE engagement.general_reports SET body = CAST(:b AS jsonb), body_sha256 = :h, audit_ids = CAST(:a AS uuid[]), "
      "title = :t, status = 'DRAFT', revision = revision + 1, needs_refresh = FALSE, auditor_signed_by = NULL, auditor_signed_at = NULL, "
      "auditor_signed_sha256 = NULL, auditor_signature_sha256 = NULL, jefe_by = NULL, jefe_at = NULL, jefe_sha256 = NULL, "
      "jefe_signature_sha256 = NULL, updated_at = now() WHERE id = CAST(:i AS uuid)",
      b=json.dumps(body, default=str), h=sha, a=audit_ids, i=rep["id"])
    _event(rep["id"], "REGENERATED", rep["status"], "DRAFT", sha, user, role,
           "Actualizado al Informe Ejecutivo con la data vigente (las aprobaciones anteriores quedan sin efecto)")
    db.session.commit()


def delete(rid):
    """Elimina un informe que ya no cumple las condiciones (con su bitácora y recepciones)."""
    for table in ("general_report_acks", "general_report_events"):
        x(f"DELETE FROM engagement.{table} WHERE report_id = CAST(:r AS uuid)", r=rid)
    x("DELETE FROM engagement.general_reports WHERE id = CAST(:r AS uuid)", r=rid)
    db.session.commit()
