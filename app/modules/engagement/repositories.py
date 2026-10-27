"""Acceso a datos de auditorías (SQL parametrizado)."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from app.extensions import db
from .templates import default_criteria, KINDS, LINES, TEMPLATE_KEYS


def q(sql, **p):
    return [dict(r._mapping) for r in db.session.execute(text(sql), p)]


def q1(sql, **p):
    r = q(sql, **p)
    return r[0] if r else None


def x(sql, **p):
    return db.session.execute(text(sql), p)


# ------------------------------------------------------------------ catálogo y expedientes
def list_units(active_only=True, domains=None):
    where = []
    params = {}

    if active_only:
        where.append("u.active")

    if domains and "ALL" not in domains:
        domains = [str(d).upper() for d in domains]

        # Auditoría Financiera puede utilizar sucursales generales.
        if domains == ["FINANCIERA"]:
            where.append(
                "(u.audit_domain = ANY(CAST(:d AS text[])) "
                "OR u.audit_domain = 'GENERAL')"
            )
        else:
            # Sistemas y demás dominios solo ven su propio dominio.
            where.append(
                "u.audit_domain = ANY(CAST(:d AS text[]))"
            )

        params["d"] = domains

    clause = (" WHERE " + " AND ".join(where)) if where else ""

    return q(
        "SELECT u.id, u.code, u.name, u.kind, u.active, "
        "u.audit_domain, u.responsible_name, u.responsible_role "
        "FROM engagement.units u"
        + clause
        + " ORDER BY u.name",
        **params,
    )

def get_unit(unit_id):
    return q1("SELECT id, code, name, kind, active, audit_domain, responsible_name, responsible_role FROM engagement.units WHERE id = CAST(:i AS integer)", i=int(unit_id))


def create_unit(code, name, kind, audit_domain="GENERAL", responsible_name=None, responsible_role=None):
    r = q1("INSERT INTO engagement.units (code, name, kind, audit_domain, responsible_name, responsible_role) VALUES (:c, :n, :k, :d, :rn, :rr) RETURNING id", c=code, n=name, k=kind, d=audit_domain, rn=responsible_name, rr=responsible_role)
    db.session.commit()
    return r["id"]


def _lock(key):
    """Serializa la asignación de correlativos de un mismo prefijo y año (se libera al confirmar)."""
    x("SELECT pg_advisory_xact_lock(hashtext(:k))", k=key)


def next_file_code(audit_type, company, year):
    """Siguiente código de expediente TIPO-COMPAÑÍA-NNN-AÑO."""
    from .codification import file_code
    _lock(f"file:{audit_type}:{company}:{year}")
    n = db.session.execute(text(
        "SELECT COALESCE(max(CAST(split_part(substring(code from length(:p) + 2), '-', 1) AS int)), 0) + 1 "
        "FROM engagement.files WHERE audit_type = :t AND company = :c AND fiscal_year = :y"),
        {"p": f"{audit_type}-{company}", "t": audit_type, "c": company, "y": year}).scalar_one()
    return file_code(audit_type, company, n, year)


def next_audit_code(file_id):
    """Código de la auditoría: el del expediente con el sufijo -A<n>."""
    from .codification import audit_code
    f = q1("SELECT code FROM engagement.files WHERE id = CAST(:f AS uuid) FOR UPDATE", f=str(file_id))
    # Correlativo siguiente entre las auditorías vigentes; una anulada libera su número.
    n = db.session.execute(text(
        "SELECT COALESCE(max(CAST(substring(code from '-A([0-9]+)$') AS int)), 0) + 1 FROM engagement.audits "
        "WHERE file_id = CAST(:f AS uuid) AND status <> 'ANULADA'"), {"f": str(file_id)}).scalar_one()
    return audit_code(f["code"], n)


def report_code_for(audit_id, kind, year):
    """Código del informe: se reutiliza para las versiones del mismo tipo; si no existe, se asigna el siguiente."""
    from .codification import report_code, report_prefix
    prev = q1("SELECT code FROM engagement.reports WHERE audit_id = CAST(:a AS uuid) AND kind = :k AND code IS NOT NULL "
              "ORDER BY version LIMIT 1", a=str(audit_id), k=kind)
    if prev:
        return prev["code"]
    a = q1("SELECT plan_type, process, frequency, report_company FROM engagement.audits WHERE id = CAST(:a AS uuid)", a=str(audit_id))
    prefix = report_prefix(a["plan_type"], a["process"], a["frequency"], a["report_company"])
    _lock(f"report:{prefix}:{year}")
    n = db.session.execute(text(
        "SELECT COALESCE(max(CAST(split_part(substring(code from length(:p) + 2), '-', 1) AS int)), 0) + 1 "
        "FROM engagement.reports WHERE code LIKE :p || '-%-' || :y"), {"p": prefix, "y": str(year)}).scalar_one()
    return report_code(prefix, n, year)


def create_file(unit_id, title, objective, pf, pt, user, audit_domain="GENERAL", audit_type="C", company="SC", year=None):
    """Crea el expediente con su código institucional; devuelve (id, código)."""
    from datetime import date
    if audit_domain not in ("GENERAL", "FINANCIERA", "SISTEMAS"):
        raise ValueError("audit_domain inválido")
    year = year or date.today().year
    fid = str(uuid.uuid4())
    code = next_file_code(audit_type, company, year)
    x("INSERT INTO engagement.files (id, code, unit_id, title, objective, period_from, period_to, audit_domain, created_by, "
      "audit_type, company, fiscal_year) VALUES (CAST(:i AS uuid), :c, :u, :t, :o, :pf, :pt, :d, CAST(:by AS uuid), :at, :co, :y)",
      i=fid, c=code, u=unit_id, t=title, o=objective, pf=pf, pt=pt, d=audit_domain, by=user, at=audit_type, co=company, y=year)
    db.session.commit()
    return fid, code


FILE_SQL = ("SELECT f.id::text, f.code, f.legacy_code, f.audit_type, f.company, f.fiscal_year, f.title, f.objective, f.period_from, f.period_to, f.status, f.audit_domain, f.created_at, u.id AS unit_id, "
            "u.code AS unit_code, u.name AS unit_name, u.kind AS unit_kind, u.audit_domain AS unit_audit_domain, u.responsible_name, u.responsible_role, "
            "(SELECT count(*) FROM engagement.audits a WHERE a.file_id = f.id AND a.status <> 'ANULADA') AS audits FROM engagement.files f JOIN engagement.units u ON u.id = f.unit_id ")


def list_files(domains=None):
    sql = FILE_SQL
    params = {}
    if domains and "ALL" not in domains:
        sql += " WHERE f.audit_domain = ANY(CAST(:d AS text[]))"
        params["d"] = domains
    return q(sql + " ORDER BY f.created_at DESC LIMIT 200", **params)


def open_file_for(unit_id, period_from, period_to):
    return q1(FILE_SQL + "WHERE f.unit_id = :u AND f.period_from = :pf AND f.period_to = :pt AND f.status = 'OPEN'",
              u=unit_id, pf=period_from, pt=period_to)


def get_file(file_id):
    return q1(FILE_SQL + "WHERE f.id = CAST(:i AS uuid)", i=str(file_id))


# ------------------------------------------------------------------ auditorías
AUDIT_SQL = ("SELECT a.id::text, a.code, a.legacy_code, a.audit_kind, a.plan_type, a.process, a.frequency, a.report_company, a.file_id::text, a.modality, a.phase, a.status, a.audit_domain, a.objectives, a.scope, a.procedures, a.lines, "
             "a.planned_start, a.planned_end, a.location, a.contact_name, a.contact_role, a.manual_score, a.manual_reason, a.manual_at, "
             "a.pac_sent_at, a.pac_sent_to, a.created_at, f.code AS file_code, f.audit_type, f.company, f.title, f.period_from, f.period_to, "
             "u.code AS unit_code, u.name AS unit_name, u.kind AS unit_kind, u.audit_domain AS unit_audit_domain, u.responsible_name, u.responsible_role "
             "FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id JOIN engagement.units u ON u.id = f.unit_id ")


def list_audits(statuses=None, domains=None):
    sql = AUDIT_SQL
    params = {}
    where = ["a.status <> 'ANULADA'"]
    if statuses:
        where.append("a.status = ANY(CAST(:st AS text[]))")
        params["st"] = statuses
    if domains and "ALL" not in domains:
        where.append("a.audit_domain = ANY(CAST(:d AS text[]))")
        params["d"] = domains
    if where:
        sql += " WHERE " + " AND ".join(where)
    return q(sql + " ORDER BY a.created_at DESC LIMIT 200", **params)


def get_audit(audit_id):
    return q1(AUDIT_SQL + "WHERE a.id = CAST(:i AS uuid) AND a.status <> 'ANULADA'", i=str(audit_id))


def team(audit_id):
    """Equipo de la auditoría con la función en el equipo (LIDER/AUDITOR) y los roles del usuario en SICAS."""
    from app.core.security.permissions import ROLE_LABELS

    rows = q("SELECT t.user_id::text AS user_id, t.role, t.initials, u.full_name AS name, u.username, "
             "COALESCE((SELECT array_agg(r.code ORDER BY r.code) FROM iam.user_roles ur JOIN iam.roles r ON r.id = ur.role_id "
             "WHERE ur.user_id = t.user_id), '{}') AS user_roles "
             "FROM engagement.team t JOIN iam.users u ON u.id = t.user_id WHERE t.audit_id = CAST(:a AS uuid) ORDER BY t.role DESC, u.full_name",
             a=str(audit_id))
    for r in rows:
        codes = list(r.get("user_roles") or [])
        r["user_roles"] = codes
        r["system_role"] = ", ".join(ROLE_LABELS.get(c, c) for c in codes) or "—"
    return rows


def is_member(audit_id, user_id) -> bool:
    return q1("SELECT 1 AS ok FROM engagement.team WHERE audit_id = CAST(:a AS uuid) AND user_id = CAST(:u AS uuid)", a=str(audit_id), u=user_id) is not None


def my_audit_ids(user_id):
    return {r["id"] for r in q("SELECT audit_id::text AS id FROM engagement.team WHERE user_id = CAST(:u AS uuid)", u=user_id)}


def eligible_auditors(domain="GENERAL"):
    role_map = {
        "GENERAL": ["AUDITOR"],
        "FINANCIERA": ["AUDITOR_FINANCIERO"],
        "SISTEMAS": ["AUDITOR_SISTEMAS"],
    }
    roles = role_map.get(domain)
    if not roles:
        return []
    return q("SELECT u.id::text AS id, u.full_name AS name, u.username FROM iam.users u "
             "JOIN iam.user_roles ur ON ur.user_id = u.id JOIN iam.roles r ON r.id = ur.role_id "
             "WHERE r.code = ANY(CAST(:roles AS text[])) AND u.is_active ORDER BY u.full_name", roles=roles)


def create_audit(file_id, d, members, user):
    """Crea la auditoría con el código del expediente y sufijo -A<n>; devuelve (id, código)."""
    aid = str(uuid.uuid4())
    code = next_audit_code(file_id)
    domain = d.get("audit_domain", "GENERAL")
    # Sistemas inicia en Levantamiento de información; el resto, en Planificación.
    first_phase = "LEVANTAMIENTO" if domain == "SISTEMAS" else "PLANIFICACION"
    x("INSERT INTO engagement.audits (id, code, file_id, modality, audit_domain, objectives, scope, procedures, lines, planned_start, planned_end, location, "
      "contact_name, contact_role, created_by, phase, plan_type, process, frequency, report_company, audit_kind) VALUES (CAST(:i AS uuid), :c, CAST(:f AS uuid), :m, :d, :o, :s, :p, "
      "CAST(:l AS text[]), :ps, :pe, :loc, :cn, :cr, CAST(:by AS uuid), :ph, :pl, :pr, :fr, :rc, :ak)",
      i=aid, c=code, f=str(file_id), m=d["modality"], d=domain, o=d["objectives"], s=d["scope"], p=d.get("procedures"), l=d["lines"], ps=d.get("planned_start"),
      pe=d.get("planned_end"), loc=d.get("location"), cn=d.get("contact_name"), cr=d.get("contact_role"), by=user, ph=first_phase,
      pl=d["plan_type"], pr=d["process"], fr=d["frequency"], rc=d["report_company"],
      ak=d.get("audit_kind") or ("SISTEMAS" if domain == "SISTEMAS" else "OPERATIVA"))
    for m in members:
        x("INSERT INTO engagement.team (audit_id, user_id, role, initials) VALUES (CAST(:a AS uuid), CAST(:u AS uuid), :r, :i)",
          a=aid, u=m["user_id"], r=m["role"], i=m["initials"])
    x("INSERT INTO engagement.phase_log (audit_id, from_phase, to_phase, changed_by, note) VALUES (CAST(:a AS uuid), NULL, :ph, CAST(:u AS uuid), 'Creación')", a=aid, u=user, ph=first_phase)
    db.session.commit()
    return aid, code


def _insert_phase_score_snapshot(snapshot):
    x(
        "INSERT INTO engagement.phase_score_snapshots "
        "(audit_id, phase_log_id, report_id, report_version, phase, trigger_action, "
        "captured_by, captured_username, scorecard) "
        "VALUES (CAST(:a AS uuid), CAST(:pl AS bigint), CAST(:rid AS uuid), "
        "CAST(:rv AS integer), :phase, :action, CAST(:u AS uuid), :username, "
        "CAST(:scorecard AS jsonb))",
        a=str(snapshot["audit_id"]),
        pl=snapshot.get("phase_log_id"),
        rid=snapshot.get("report_id"),
        rv=snapshot.get("report_version"),
        phase=snapshot["phase"],
        action=snapshot["trigger_action"],
        u=str(snapshot["captured_by"]),
        username=snapshot.get("captured_username"),
        scorecard=json.dumps(snapshot["scorecard"], ensure_ascii=False, default=str),
    )


def change_phase(audit_id, from_phase, to_phase, user, note, phase_snapshot=None, phase_score=None):
    """Cambia la fase; con phase_score (Sistemas, al avanzar) congela las respuestas y la nota de la fase cerrada."""
    x("UPDATE engagement.audits SET phase=:t WHERE id = CAST(:a AS uuid)",
      t=to_phase, a=str(audit_id))
    if phase_score:
        x("UPDATE engagement.items i SET phase_results = i.phase_results || jsonb_build_object(CAST(:p AS text), "
          "jsonb_build_object('results', i.results, 'manual_score', i.manual_score, 'manual_reason', i.manual_reason)) "
          "FROM engagement.worksheets w WHERE w.id = i.worksheet_id AND w.audit_id = CAST(:a AS uuid)",
          p=from_phase, a=str(audit_id))
        x("INSERT INTO engagement.audit_phase_scores (audit_id, phase, score, rating, detail, closed_by) "
          "VALUES (CAST(:a AS uuid), :p, :s, :r, CAST(:d AS jsonb), CAST(:u AS uuid)) "
          "ON CONFLICT (audit_id, phase) DO UPDATE SET score = EXCLUDED.score, rating = EXCLUDED.rating, "
          "detail = EXCLUDED.detail, closed_by = EXCLUDED.closed_by, closed_at = clock_timestamp()",
          a=str(audit_id), p=from_phase, s=phase_score["score"], r=phase_score["rating"],
          d=json.dumps(phase_score.get("detail") or {}, ensure_ascii=False, default=str), u=user)
    phase_log_id = x(
        "INSERT INTO engagement.phase_log "
        "(audit_id, from_phase, to_phase, changed_by, note) "
        "VALUES (CAST(:a AS uuid), :f, :t, CAST(:u AS uuid), :n) RETURNING id",
        a=str(audit_id), f=from_phase, t=to_phase, u=user, n=note,
    ).scalar_one()
    if phase_snapshot:
        snapshot = dict(phase_snapshot)
        snapshot["phase_log_id"] = phase_log_id
        _insert_phase_score_snapshot(snapshot)
    db.session.commit()


def phase_log(audit_id):
    return q("SELECT l.from_phase, l.to_phase, l.changed_at, u.username, l.note FROM engagement.phase_log l JOIN iam.users u ON u.id = l.changed_by "
             "WHERE l.audit_id = CAST(:a AS uuid) ORDER BY l.id", a=str(audit_id))


def phase_snapshots(audit_id):
    rows = q(
        "SELECT id::text, audit_id::text, phase_log_id, report_id::text, "
        "report_version, phase, trigger_action, captured_at, captured_by::text, "
        "captured_username, scorecard FROM engagement.phase_score_snapshots "
        "WHERE audit_id = CAST(:a AS uuid) ORDER BY captured_at, id",
        a=str(audit_id),
    )
    # El detalle de respuestas y criterios permanece guardado en la instantánea,
    # pero el resumen solo entrega los indicadores necesarios para comparar.
    from .score_snapshots import compare

    previous = None
    for row in rows:
        full = row.get("scorecard") or {}
        row["variation"] = compare(previous, full)
        previous = full
    for row in rows:
        card = dict(row.get("scorecard") or {})
        card.pop("evidence", None)
        card["worksheets"] = [
            {
                key: value
                for key, value in sheet.items()
                if key not in ("criteria", "items_detail")
            }
            for sheet in card.get("worksheets", [])
        ]
        row["scorecard"] = card
    return rows


def set_audit_manual(audit_id, score, reason, user):
    x("UPDATE engagement.audits SET manual_score=:s, manual_reason=:r, manual_by=CAST(:u AS uuid), manual_at=now() WHERE id = CAST(:a AS uuid)",
      s=score, r=reason, u=user, a=str(audit_id))
    db.session.commit()


AUDIT_EDITABLE = ("modality", "objectives", "scope", "procedures", "location", "contact_name", "contact_role",
                  "plan_type", "process", "frequency", "report_company",
                  "planned_start", "planned_end")


def update_audit_data(audit_id, d):
    """Actualiza los datos generales de la auditoría (columnas de lista fija)."""
    cols = [c for c in AUDIT_EDITABLE if c in d]
    if not cols:
        return
    x("UPDATE engagement.audits SET " + ", ".join(f"{c} = :{c}" for c in cols) + " WHERE id = CAST(:a AS uuid)",
      **{c: d[c] for c in cols}, a=str(audit_id))
    db.session.commit()


# ------------------------------------------------------------------ plantillas, cédulas e ítems
def get_template(kind, line):
    r = q1("SELECT criteria, version FROM engagement.templates WHERE kind=:k AND line=:l", k=kind, l=line)
    return (r["criteria"], r["version"]) if r else (default_criteria(kind, line), 0)


def list_templates(keys=None):
    allowed = tuple(keys) if keys is not None else TEMPLATE_KEYS
    saved = {(r["kind"], r["line"]): r for r in q(
        "SELECT kind, line, version, criteria, updated_at FROM engagement.templates"
    )}
    return [
        {
            "kind": kind,
            "line": line,
            "version": saved[(kind, line)]["version"] if (kind, line) in saved else 0,
            "criteria": saved[(kind, line)]["criteria"] if (kind, line) in saved else default_criteria(kind, line),
            "customized": (kind, line) in saved,
        }
        for kind, line in allowed
    ]


def save_template(kind, line, criteria, user):
    x("INSERT INTO engagement.templates (kind, line, version, criteria, updated_by) VALUES (:k, :l, 1, CAST(:c AS jsonb), CAST(:u AS uuid)) "
      "ON CONFLICT (kind, line) DO UPDATE SET version = engagement.templates.version + 1, criteria = EXCLUDED.criteria, updated_by = EXCLUDED.updated_by, updated_at = now()",
      k=kind, l=line, c=json.dumps(criteria), u=user)
    db.session.commit()


def create_worksheet(audit_id, kind, line, criteria, version, user):
    wid = str(uuid.uuid4())
    x("INSERT INTO engagement.worksheets (id, audit_id, kind, line, title, criteria, template_version, created_by) "
      "VALUES (CAST(:i AS uuid), CAST(:a AS uuid), :k, :l, :t, CAST(:c AS jsonb), :v, CAST(:u AS uuid))",
      i=wid, a=str(audit_id), k=kind, l=line, t=f"{KINDS[kind]} — {LINES[line]}", c=json.dumps(criteria), v=version, u=user)
    db.session.commit()
    return wid

def get_financial_template(kind, line):
    """
    Obtiene una plantilla financiera del catálogo 012 y sus criterios.

    No utiliza engagement.templates, porque las cédulas financieras
    utilizan el catálogo oficial de engagement.financial_templates.
    """
    kind = str(kind).upper().strip()
    line = str(line).upper().strip()

    template = q1(
        """
        SELECT
            ft.code,
            ft.kind,
            ft.line,
            ft.title,
            ft.version,
            ft.source_file,
            ft.source_sheet,
            ft.source_sha256
        FROM engagement.financial_templates ft
        WHERE ft.kind = :k
          AND ft.line = :l
          AND ft.active = TRUE
        LIMIT 1
        """,
        k=kind,
        l=line,
    )

    if template is None:
        return None

    criteria = q(
        """
        SELECT
            fc.id::text AS id,
            fc.source_id,
            fc.section,
            fc.subsection,
            fc.criterion_text,
            fc.sort_order,
            fc.excel_row,
            fc.weight,
            fc.metadata
        FROM engagement.financial_criteria fc
        WHERE fc.template_code = :t
        ORDER BY fc.sort_order
        """,
        t=template["code"],
    )

    if not criteria:
        raise ValueError(
            f"La plantilla financiera {template['code']} no tiene criterios cargados"
        )

    template["criteria"] = criteria
    return template


def create_financial_worksheet(audit_id, kind, line, user):
    """
    Crea una cédula financiera usando el catálogo financiero oficial.

    La worksheet operativa sigue siendo engagement.worksheets, pero además
    queda registrada en engagement.financial_worksheets mediante la función
    SQL de la migración 013.

    Todo se confirma en UNA sola transacción.
    """
    audit_id = str(audit_id)
    user = str(user)
    kind = str(kind).upper().strip()
    line = str(line).upper().strip()

    template = get_financial_template(kind, line)

    if template is None:
        raise ValueError(
            f"No existe una plantilla financiera activa para "
            f"{kind}/{line}"
        )

    criteria = []

    for row in template["criteria"]:
        criterion = {
            "code": row["source_id"],
            "text": row["criterion_text"],
            "source_id": row["source_id"],
            "section": row["section"],
            "subsection": row["subsection"],
            "evaluation_mode": "FINANCIAL_CATALOG",
            "template_code": template["code"],
            "source_excel_row": row["excel_row"],
            "metadata": row["metadata"] or {},
        }

        # Cédulas tipo cuestionario: bloque y peso del bloque (scoring.questionnaire_summary).
        meta = row["metadata"] or {}
        if meta.get("block"):
            criterion.update(block=str(meta["block"]), block_title=meta.get("block_title") or row["section"],
                             block_weight=meta.get("block_weight"), number=meta.get("number"))

        # El Excel financiero actualmente no define pesos individuales.
        # El motor actual puede tratar la ausencia del peso como peso 1
        # mientras se define formalmente la metodología financiera.
        if row["weight"] is not None:
            criterion["weight"] = row["weight"]

        criteria.append(criterion)

    worksheet_id = str(uuid.uuid4())

    title_map = {
        ("SUSCRIPCION", "AUTO"): "Suscripción Auto",
        ("RECLAMO", "AUTO"): "Reclamo / Indemnización Auto",
        ("SUSCRIPCION", "PERSONAL"): "Suscripción Personal",
        ("RECLAMO", "PERSONAL"): "Reclamo / Indemnización Personal",
        ("SUSCRIPCION", "PATRIMONIAL"): "Suscripción Patrimonial",
        ("RECLAMO", "PATRIMONIAL"): "Reclamo / Indemnización Patrimonial",
    }

    title = title_map.get(
        (kind, line),
        template["title"],
    )[:180]

    try:
        x(
            """
            INSERT INTO engagement.worksheets
            (
                id,
                audit_id,
                kind,
                line,
                title,
                criteria,
                template_version,
                created_by
            )
            VALUES
            (
                CAST(:i AS uuid),
                CAST(:a AS uuid),
                :k,
                :l,
                :t,
                CAST(:c AS jsonb),
                :v,
                CAST(:u AS uuid)
            )
            """,
            i=worksheet_id,
            a=audit_id,
            k=kind,
            l=line,
            t=title,
            c=json.dumps(criteria),
            v=template["version"],
            u=user,
        )

        x(
            """
            SELECT engagement.register_financial_worksheet(
                CAST(:w AS uuid),
                :t,
                CAST(:u AS uuid)
            )
            """,
            w=worksheet_id,
            t=template["code"],
            u=user,
        )
        for criterion in criteria:
            x(
                """
                INSERT INTO engagement.items
                    (id, worksheet_id, ref, source, updated_by)
                VALUES
                    (
                        CAST(:i AS uuid),
                        CAST(:w AS uuid),
                        :r,
                        'ONLINE',
                        CAST(:u AS uuid)
                    )
                ON CONFLICT (worksheet_id, ref) DO NOTHING
                """,
                i=str(uuid.uuid4()),
                w=worksheet_id,
                r=criterion["code"],
                u=user,
            )

        db.session.commit()

        return worksheet_id

    except Exception:
        db.session.rollback()
        raise

    
def system_worksheet(audit_id, user):
    existing = q1("SELECT id::text FROM engagement.worksheets WHERE audit_id = CAST(:a AS uuid) AND kind = 'SISTEMAS' AND line = 'ERP_TI'", a=str(audit_id))
    if existing:
        return existing["id"]
    criteria, version = get_template("SISTEMAS", "ERP_TI")
    wid = str(uuid.uuid4())
    x("INSERT INTO engagement.worksheets (id, audit_id, kind, line, title, criteria, template_version, created_by) "
      "VALUES (CAST(:i AS uuid), CAST(:a AS uuid), 'SISTEMAS', 'ERP_TI', :t, CAST(:c AS jsonb), :v, CAST(:u AS uuid))",
      i=wid, a=str(audit_id), t="Auditoría de Sistemas — ERP / TI", c=json.dumps(criteria), v=version, u=user)
    for c in criteria:
        x("INSERT INTO engagement.items (id, worksheet_id, ref, source, updated_by) VALUES (CAST(:i AS uuid), CAST(:w AS uuid), :r, 'ONLINE', CAST(:u AS uuid)) ON CONFLICT (worksheet_id, ref) DO NOTHING",
          i=str(uuid.uuid4()), w=wid, r=c["code"], u=user)
    db.session.commit()
    return wid


def replace_system_questionnaire(worksheet_id, criteria, user, title=None):
    """Reconfigura una cédula de Sistemas con un cuestionario importado.

    Solo se permite cuando la cédula no tiene respuestas, observaciones ni
    evidencias asociadas a sus ítems. Así se evita destruir información de
    auditoría. Los controles importados pasan a ser la base real de la cédula;
    los controles adicionales se agregan después manualmente.
    """
    ws_id = str(worksheet_id)
    existing = q("SELECT id::text, results, observation, info_exception, manual_score, manual_reason "
                 "FROM engagement.items WHERE worksheet_id = CAST(:w AS uuid)", w=ws_id)
    if any((r.get("results") or {}) or r.get("observation") or r.get("info_exception") or r.get("manual_score") is not None
           or r.get("manual_reason") for r in existing):
        raise ValueError("La cédula ya contiene respuestas o ajustes; no se puede reemplazar su estructura mediante Excel")
    evidence = q1("SELECT id::text FROM engagement.evidence WHERE item_id IN "
                   "(SELECT id FROM engagement.items WHERE worksheet_id = CAST(:w AS uuid)) LIMIT 1", w=ws_id)
    observations = q1("SELECT id::text FROM engagement.observations WHERE item_id IN "
                      "(SELECT id FROM engagement.items WHERE worksheet_id = CAST(:w AS uuid)) LIMIT 1", w=ws_id)
    if evidence or observations:
        raise ValueError("La cédula ya tiene evidencias u observaciones; no se puede reemplazar su estructura mediante Excel")

    # Los ítems están vacíos, por lo que es seguro recrearlos con los controles
    # reales del archivo recibido.
    x("DELETE FROM engagement.items WHERE worksheet_id = CAST(:w AS uuid)", w=ws_id)
    x("UPDATE engagement.worksheets SET criteria = CAST(:c AS jsonb), template_version = template_version + 1, "
      "title = COALESCE(:t, title), updated_at = now() WHERE id = CAST(:w AS uuid)",
      c=json.dumps(criteria, ensure_ascii=False), t=title, w=ws_id)
    for c in criteria:
        x("INSERT INTO engagement.items (id, worksheet_id, ref, source, updated_by) "
          "VALUES (CAST(:i AS uuid), CAST(:w AS uuid), :r, 'ONLINE', CAST(:u AS uuid)) "
          "ON CONFLICT (worksheet_id, ref) DO NOTHING",
          i=str(uuid.uuid4()), w=ws_id, r=c["code"], u=user)
    db.session.commit()


def add_system_control(worksheet_id, text, section, weight, user):
    """Agrega un control de Sistemas manualmente, sin inventar su contenido."""
    ws = q1("SELECT criteria FROM engagement.worksheets WHERE id = CAST(:w AS uuid)", w=str(worksheet_id))
    if not ws:
        raise ValueError("Cédula no encontrada")
    criteria = list(ws.get("criteria") or [])
    existing_codes = {str(c.get("code", "")) for c in criteria}
    n = 1
    while f"MAN{n:03d}" in existing_codes:
        n += 1
    if n > 999:
        raise ValueError("Se alcanzó el máximo de controles manuales")
    code = f"MAN{n:03d}"
    criterion = {
        "code": code,
        "text": str(text).strip(),
        "weight": int(weight),
        "section": str(section).strip() or "Seguridad de TI",
        "evaluation_mode": "SEC_TI",
        "source_id": None,
        "manual_control": True,
    }
    criteria.append(criterion)
    x("UPDATE engagement.worksheets SET criteria = CAST(:c AS jsonb), updated_at = now() WHERE id = CAST(:w AS uuid)",
      c=json.dumps(criteria, ensure_ascii=False), w=str(worksheet_id))
    x("INSERT INTO engagement.items (id, worksheet_id, ref, source, updated_by) VALUES (CAST(:i AS uuid), CAST(:w AS uuid), :r, 'ONLINE', CAST(:u AS uuid))",
      i=str(uuid.uuid4()), w=str(worksheet_id), r=code, u=user)
    db.session.commit()
    return code


def system_item_map(worksheet_id):
    return {r["ref"]: r for r in q("SELECT id::text, ref, results, observation, info_exception FROM engagement.items WHERE worksheet_id = CAST(:w AS uuid)", w=str(worksheet_id))}


def update_system_item(item_id, results, observation, info_exception, auto_score, user, source="ONLINE"):
    x("UPDATE engagement.items SET results = CAST(:r AS jsonb), observation = :o, info_exception = :e, auto_score = :a, source = :s, updated_by = CAST(:u AS uuid), updated_at = now() WHERE id = CAST(:i AS uuid)",
      r=json.dumps(results), o=observation, e=info_exception, a=auto_score, s=source, u=user, i=str(item_id))
    x("UPDATE engagement.worksheets SET updated_at = now() WHERE id = (SELECT worksheet_id FROM engagement.items WHERE id = CAST(:i AS uuid))", i=str(item_id))


WS_SQL = ("SELECT id::text, audit_id::text, kind, line, title, criteria, template_version, status, manual_score, manual_reason, updated_at "
          "FROM engagement.worksheets ")
ITEM_SQL = ("SELECT id::text, worksheet_id::text, ref, results, auto_score, manual_score, manual_reason, observation, info_exception, source, updated_at, "
            "phase_results FROM engagement.items ")


FINANCIAL_TEMPLATE_CODES = {
    ("SUSCRIPCION", "AUTO"): "FIN_AUTO_SUSCRIPCION",
    ("RECLAMO", "AUTO"): "FIN_AUTO_RECLAMO",
    ("SUSCRIPCION", "PERSONAL"): "FIN_PERSONAL_SUSCRIPCION",
    ("RECLAMO", "PERSONAL"): "FIN_PERSONAL_RECLAMO",
    ("SUSCRIPCION", "PATRIMONIAL"): "FIN_PATRIMONIAL_SUSCRIPCION",
    ("RECLAMO", "PATRIMONIAL"): "FIN_PATRIMONIAL_RECLAMO",
}


def _hydrate_financial_template_code(ws):
    """
    Compatibilidad con cédulas financieras creadas antes de que
    template_code formara parte del criterio operativo.

    No modifica PostgreSQL: solo completa en memoria el dato
    necesario para el evaluador financiero.
    """
    if not ws:
        return ws

    kind = str(ws.get("kind") or "").upper().strip()
    line = str(ws.get("line") or "").upper().strip()
    template_code = FINANCIAL_TEMPLATE_CODES.get((kind, line))

    if not template_code:
        return ws

    criteria = ws.get("criteria") or []

    for criterion in criteria:
        if (
            str(criterion.get("evaluation_mode") or "").upper()
            == "FINANCIAL_CATALOG"
            and not criterion.get("template_code")
        ):
            criterion["template_code"] = template_code

    ws["criteria"] = criteria
    return ws


def worksheets_with_items(audit_id):
    sheets = q(WS_SQL + "WHERE audit_id = CAST(:a AS uuid) ORDER BY kind, line", a=str(audit_id))
    for ws in sheets:
        _hydrate_financial_template_code(ws)
        ws["items"] = q(ITEM_SQL + "WHERE worksheet_id = CAST(:w AS uuid) ORDER BY ref", w=ws["id"])
    return sheets


def get_worksheet(ws_id, with_items=True):
    ws = q1(WS_SQL + "WHERE id = CAST(:i AS uuid)", i=str(ws_id))
    _hydrate_financial_template_code(ws)
    if ws and with_items:
        ws["items"] = q(ITEM_SQL + "WHERE worksheet_id = CAST(:w AS uuid) ORDER BY ref", w=ws["id"])
    return ws


def get_item(item_id):
    return q1(ITEM_SQL.replace("FROM engagement.items", "FROM engagement.items") + "WHERE id = CAST(:i AS uuid)", i=str(item_id))


def add_items(ws_id, refs, user, source="ONLINE"):
    n = 0
    for ref in refs:
        n += x("INSERT INTO engagement.items (id, worksheet_id, ref, source, updated_by) VALUES (CAST(:i AS uuid), CAST(:w AS uuid), :r, :s, CAST(:u AS uuid)) "
               "ON CONFLICT (worksheet_id, ref) DO NOTHING", i=str(uuid.uuid4()), w=str(ws_id), r=ref, s=source, u=user).rowcount
    db.session.commit()
    return n


def sample_refs(kind, line, branches, pf, pt, n, existing):
    if kind == "SUSCRIPCION":
        rows = q("SELECT DISTINCT policy_number AS ref FROM insurance.policies WHERE start_date BETWEEN :pf AND :pt AND upper(branch) = ANY(CAST(:b AS text[])) "
                 "AND NOT (policy_number = ANY(CAST(:e AS text[]))) ORDER BY random() LIMIT :n", pf=pf, pt=pt, b=branches, e=list(existing), n=n)
    else:
        rows = q("SELECT DISTINCT c.claim_number AS ref FROM insurance.claims c JOIN LATERAL (SELECT branch FROM insurance.policies p WHERE p.policy_number = c.policy_number LIMIT 1) p ON TRUE "
                 "WHERE c.occurrence_date BETWEEN :pf AND :pt AND upper(p.branch) = ANY(CAST(:b AS text[])) AND NOT (c.claim_number = ANY(CAST(:e AS text[]))) "
                 "ORDER BY random() LIMIT :n", pf=pf, pt=pt, b=branches, e=list(existing), n=n)
    return [r["ref"] for r in rows]


def update_item(item_id, results, observation, info_exception, auto_score, user, source="ONLINE"):
    x("UPDATE engagement.items SET results = CAST(:r AS jsonb), observation = :o, info_exception = :e, auto_score = :a, source = :s, "
      "updated_by = CAST(:u AS uuid), updated_at = now() WHERE id = CAST(:i AS uuid)",
      r=json.dumps(results), o=observation, e=info_exception, a=auto_score, s=source, u=user, i=str(item_id))
    x("UPDATE engagement.worksheets SET updated_at = now() WHERE id = (SELECT worksheet_id FROM engagement.items WHERE id = CAST(:i AS uuid))", i=str(item_id))
    db.session.commit()


def set_item_manual(item_id, score, reason, user):
    x("UPDATE engagement.items SET manual_score=:s, manual_reason=:r, manual_by=CAST(:u AS uuid), manual_at=CASE WHEN :s IS NULL THEN NULL ELSE now() END, "
      "updated_at=now(), updated_by=CAST(:u AS uuid) WHERE id = CAST(:i AS uuid)", s=score, r=reason, u=user, i=str(item_id))
    db.session.commit()


def set_ws_manual(ws_id, score, reason, user):
    x("UPDATE engagement.worksheets SET manual_score=:s, manual_reason=:r, manual_by=CAST(:u AS uuid), manual_at=now(), updated_at=now() WHERE id = CAST(:i AS uuid)",
      s=score, r=reason, u=user, i=str(ws_id))
    db.session.commit()


# ------------------------------------------------------------------ observaciones y evidencias
OBS_SQL = ("SELECT id::text, audit_id::text, item_id::text, seq, title, condition, criteria, cause, effect, recommendation, risk, unit_decision, unit_response, "
           "unit_response_at, pac_action, pac_owner, pac_due, pac_status, origin, covered_items::text[] AS covered_items, "
           "superseded_by::text AS superseded_by FROM engagement.observations ")


def observations(audit_id):
    """Observaciones vigentes (las reemplazadas por una consolidación quedan fuera)."""
    return q(OBS_SQL + "WHERE audit_id = CAST(:a AS uuid) AND superseded_by IS NULL ORDER BY seq", a=str(audit_id))


def get_observation(oid):
    return q1(OBS_SQL + "WHERE id = CAST(:i AS uuid)", i=str(oid))


def _insert_observation_revision(oid, user, changed_fields=(), reason=None, report_status=None):
    """Guarda la observación tal como queda tras el cambio, con el número de revisión siguiente."""
    x("INSERT INTO engagement.observation_revisions (observation_id, revision, data, changed_fields, reason, report_status, created_by) "
      "SELECT o.id, COALESCE((SELECT max(revision) FROM engagement.observation_revisions r WHERE r.observation_id = o.id), 0) + 1, "
      "to_jsonb(o) - 'id' - 'audit_id' - 'seq' - 'created_by' - 'created_at' - 'updated_at', "
      ":f, :r, :st, CAST(:u AS uuid) FROM engagement.observations o WHERE o.id = CAST(:i AS uuid)",
      i=str(oid), f=list(changed_fields), r=reason, st=report_status, u=user)


def add_observation(audit_id, d, user, origin="MANUAL", commit=True):
    oid = str(uuid.uuid4())
    seq = db.session.execute(text("SELECT COALESCE(max(seq), 0) + 1 FROM engagement.observations WHERE audit_id = CAST(:a AS uuid)"), {"a": str(audit_id)}).scalar_one()
    covered = d.get("covered_items") or ([d["item_id"]] if d.get("item_id") else [])
    x("INSERT INTO engagement.observations (id, audit_id, item_id, seq, title, condition, criteria, cause, effect, recommendation, risk, created_by, origin, "
      "covered_items, rule_key) VALUES (CAST(:i AS uuid), CAST(:a AS uuid), CAST(:it AS uuid), :s, :t, :c, :cr, :ca, :e, :r, :k, CAST(:u AS uuid), :o, "
      "CAST(:cov AS uuid[]), :rk)",
      i=oid, a=str(audit_id), it=d.get("item_id"), s=seq, t=d["title"], c=d["condition"], cr=d.get("criteria"), ca=d.get("cause"), e=d.get("effect"),
      r=d.get("recommendation"), k=d["risk"], u=user, o=origin, cov=[str(c) for c in covered], rk=d.get("rule_key"))
    _insert_observation_revision(oid, user, reason="Registro original" if origin == "MANUAL" else "Redactada por el motor de reglas al cargar la cédula")
    if commit:
        db.session.commit()
    return oid, seq


def observed_item_ids(audit_id, exclude=()):
    """Ítems ya cubiertos por una observación vigente (no se generan duplicadas)."""
    rows = q("SELECT id::text AS id, item_id::text AS item_id, covered_items::text[] AS covered FROM engagement.observations "
             "WHERE audit_id = CAST(:a AS uuid) AND superseded_by IS NULL", a=str(audit_id))
    out = set()
    for r in rows:
        if r["id"] in exclude:
            continue
        out.update(c for c in (r["covered"] or []) if c)
        if r["item_id"]:
            out.add(r["item_id"])
    return out


def active_rule_keys(audit_id):
    """Reglas que ya tienen una observación automática vigente en la auditoría."""
    return {r["rule_key"] for r in q("SELECT rule_key FROM engagement.observations WHERE audit_id = CAST(:a AS uuid) "
                                     "AND rule_key IS NOT NULL AND superseded_by IS NULL", a=str(audit_id))}


def regulatory_catalog(include_inactive=False):
    return q("SELECT topic, label, keywords, criteria, cause, effect, recommendation, sort_order, active, updated_at "
             "FROM engagement.regulatory_catalog"
             + ("" if include_inactive else " WHERE active")
             + " ORDER BY sort_order, topic")


def systems_rule_catalog(include_inactive=False):
    return q("SELECT domain_key, label, keywords, criteria, cause, effect, recommendation, field_test, critical, "
             "sort_order, active, updated_at FROM engagement.systems_rule_catalog"
             + ("" if include_inactive else " WHERE active")
             + " ORDER BY sort_order, domain_key")


def update_regulatory_topic(topic, d, user):
    cols = [c for c in ("label", "criteria", "cause", "effect", "recommendation") if c in d]
    row = x("UPDATE engagement.regulatory_catalog SET " + ", ".join(f"{c} = :{c}" for c in cols)
            + (", keywords = CAST(:kw AS text[])" if "keywords" in d else "")
            + ", updated_by = CAST(:u AS uuid), updated_at = now() WHERE topic = :t RETURNING topic",
            **{c: d[c] for c in cols}, kw=d.get("keywords"), u=user, t=topic).first()
    db.session.commit()
    return row is not None


def consolidable_auto_observations(audit_id):
    """Observaciones automáticas vigentes que nadie editó (solo tienen su revisión original)."""
    return q("SELECT o.id::text AS id, o.covered_items::text[] AS covered FROM engagement.observations o "
             "WHERE o.audit_id = CAST(:a AS uuid) AND o.origin = 'AUTO' AND o.superseded_by IS NULL "
             "AND cardinality(o.covered_items) <= 1 "
             "AND (SELECT count(*) FROM engagement.observation_revisions r WHERE r.observation_id = o.id) = 1", a=str(audit_id))


def supersede_observations(ids, new_id):
    x("UPDATE engagement.observations SET superseded_by = CAST(:n AS uuid), updated_at = now() "
      "WHERE id = ANY(CAST(:ids AS uuid[])) AND superseded_by IS NULL", n=str(new_id), ids=list(ids))


def audit_phase_scores(audit_id):
    return {r["phase"]: r for r in q("SELECT s.phase, s.score, s.rating, s.detail, s.closed_at, u.username AS closed_by_name "
                                      "FROM engagement.audit_phase_scores s LEFT JOIN iam.users u ON u.id = s.closed_by "
                                      "WHERE s.audit_id = CAST(:a AS uuid)", a=str(audit_id))}


OBS_FIELDS = ("title", "condition", "criteria", "cause", "effect", "recommendation", "risk", "unit_decision", "unit_response", "unit_response_at",
              "pac_action", "pac_owner", "pac_due", "pac_status")


def update_observation(oid, d, user, reason, report_status=None):
    """Actualiza la observación y guarda la revisión resultante en la misma transacción."""
    cols = [f for f in OBS_FIELDS if f in d]                       # nombres de columna de lista fija
    if not cols:
        return
    x("UPDATE engagement.observations SET " + ", ".join(f"{c} = :{c}" for c in cols) + ", updated_at = now() WHERE id = CAST(:i AS uuid)",
      **{c: d[c] for c in cols}, i=str(oid))
    _insert_observation_revision(oid, user, cols, reason, report_status)
    db.session.commit()


def observation_revisions(audit_id):
    """Revisiones de las observaciones de la auditoría, de la más antigua a la más reciente."""
    return q("SELECT r.observation_id::text, r.revision, r.data, r.changed_fields, r.reason, r.report_status, r.created_at, "
             "u.username FROM engagement.observation_revisions r JOIN engagement.observations o ON o.id = r.observation_id "
             "LEFT JOIN iam.users u ON u.id = r.created_by WHERE o.audit_id = CAST(:a AS uuid) ORDER BY o.seq, r.revision",
             a=str(audit_id))


def add_evidence(audit_id, item_id, observation_id, filename, ctype, size, sha, key, desc, user):
    eid = str(uuid.uuid4())
    x("INSERT INTO engagement.evidence (id, audit_id, item_id, observation_id, filename, content_type, size_bytes, sha256, object_key, description, uploaded_by) "
      "VALUES (CAST(:i AS uuid), CAST(:a AS uuid), CAST(:it AS uuid), CAST(:o AS uuid), :f, :c, :z, :h, :k, :d, CAST(:u AS uuid))",
      i=eid, a=str(audit_id), it=item_id, o=observation_id, f=filename, c=ctype, z=size, h=sha, k=key, d=desc, u=user)
    db.session.commit()
    return eid


def evidence(audit_id):
    return q("SELECT e.id::text, e.filename, e.content_type, e.size_bytes, e.sha256, e.description, e.uploaded_at, u.username AS uploaded_by, "
             "e.item_id::text, e.observation_id::text, (SELECT ref FROM engagement.items i WHERE i.id = e.item_id) AS item_ref "
             "FROM engagement.evidence e JOIN iam.users u ON u.id = e.uploaded_by WHERE e.audit_id = CAST(:a AS uuid) ORDER BY e.uploaded_at", a=str(audit_id))


def get_evidence(eid):
    return q1("SELECT id::text, audit_id::text, filename, content_type, sha256, object_key FROM engagement.evidence WHERE id = CAST(:i AS uuid)", i=str(eid))


# ------------------------------------------------------------------ informes
REP_SQL = ("SELECT r.id::text, r.audit_id::text, r.kind, r.code, r.version, r.status, r.body, r.body_sha256, r.created_at, r.updated_at, r.submitted_at, "
           "r.approved_at, r.approved_by::text, r.approved_body_sha256, "
           "r.jefe_approved_by::text AS jefe_approved_by, r.jefe_approved_body_sha256, "
           "r.gerente_approved_by::text AS gerente_approved_by, r.gerente_approved_body_sha256, "
           "r.contralor_approved_by::text AS contralor_approved_by, r.contralor_approved_body_sha256, "
           "r.created_by::text, r.sent_to, r.sent_at, c.username AS created_by_name, a.username AS approved_by_name "
           "FROM engagement.reports r JOIN iam.users c ON c.id = r.created_by LEFT JOIN iam.users a ON a.id = r.approved_by ")


def reports(audit_id):
    rows = q(REP_SQL + "WHERE r.audit_id = CAST(:a AS uuid) ORDER BY r.kind, r.version DESC", a=str(audit_id))
    for r in rows:
        r.pop("body", None)
    return rows


def get_report(rid):
    return q1(REP_SQL + "WHERE r.id = CAST(:i AS uuid)", i=str(rid))


def next_version(audit_id, kind):
    return db.session.execute(text("SELECT COALESCE(max(version), 0) + 1 FROM engagement.reports WHERE audit_id = CAST(:a AS uuid) AND kind = :k"),
                              {"a": str(audit_id), "k": kind}).scalar_one()


def _insert_body_revision(rid, body, sha, user, reason):
    x("INSERT INTO engagement.report_body_revisions (report_id, revision, body, body_sha256, reason, created_by) "
      "SELECT CAST(:i AS uuid), COALESCE(max(revision), 0) + 1, CAST(:b AS jsonb), :h, :r, CAST(:u AS uuid) "
      "FROM engagement.report_body_revisions WHERE report_id = CAST(:i AS uuid)",
      i=str(rid), b=json.dumps(body, default=str), h=sha, r=reason, u=user)


def create_report(audit_id, kind, version, body, sha, user, reason="Generación inicial", code=None):
    rid = str(uuid.uuid4())
    x("INSERT INTO engagement.reports (id, audit_id, kind, version, body, body_sha256, created_by, code) "
      "VALUES (CAST(:i AS uuid), CAST(:a AS uuid), :k, :v, CAST(:b AS jsonb), :h, CAST(:u AS uuid), :c)",
      i=rid, a=str(audit_id), k=kind, v=version, b=json.dumps(body, default=str), h=sha, u=user, c=code)
    _insert_body_revision(rid, body, sha, user, reason)
    db.session.commit()
    return rid


def replace_body(rid, body, sha, user, reason=None, expected_sha256=None):
    """Regenerar cambia el hash: se invalidan las iniciales previas (están atadas al hash).
    El contenido anterior se conserva en report_body_revisions. Solo se aplica si el informe
    sigue editable (y, si se indica, con el contenido que se leyó)."""
    row = x("UPDATE engagement.reports SET body = CAST(:b AS jsonb), body_sha256 = :h, updated_at = now() "
            "WHERE id = CAST(:i AS uuid) AND status IN ('DRAFT', 'RETURNED') "
            "AND (CAST(:old AS text) IS NULL OR body_sha256 = :old) RETURNING id",
            b=json.dumps(body, default=str), h=sha, i=str(rid), old=expected_sha256).first()
    if row is None:
        db.session.rollback()
        raise StaleReportState("El informe cambió de estado o de contenido; recargue e intente de nuevo")
    _insert_body_revision(rid, body, sha, user, reason)
    db.session.commit()


def body_revisions(rid):
    return q("SELECT b.revision, b.body_sha256, b.reason, b.created_at, u.username FROM engagement.report_body_revisions b "
             "LEFT JOIN iam.users u ON u.id = b.created_by WHERE b.report_id = CAST(:r AS uuid) ORDER BY b.revision", r=str(rid))


def latest_final(audit_id):
    return q1("SELECT id::text, version, status, body_sha256 FROM engagement.reports WHERE audit_id = CAST(:a AS uuid) "
              "AND kind = 'FINAL' ORDER BY version DESC LIMIT 1", a=str(audit_id))


def reopening(rid):
    return q1("SELECT o.reason, o.authorized_at, u.username FROM engagement.report_reopenings o LEFT JOIN iam.users u ON u.id = o.authorized_by "
              "WHERE o.report_id = CAST(:r AS uuid)", r=str(rid))


def reopen_report(rid, reason, user):
    """Autoriza (una sola vez) que el equipo emita una nueva versión del informe firmado; el firmado no cambia."""
    x("INSERT INTO engagement.report_reopenings (report_id, reason, authorized_by) VALUES (CAST(:r AS uuid), :t, CAST(:u AS uuid))",
      r=str(rid), t=reason, u=user)
    db.session.commit()


# ------------------------------------------------------------------ bitácora por expediente
def stage_change(ev):
    """Agrega el evento a la transacción en curso, sin confirmar: el commit del cambio de negocio lo confirma."""
    x("INSERT INTO engagement.change_events (audit_id, report_id, entity_type, entity_id, action, changes, reason, audit_phase, "
      "report_status, actor_id, actor_username, actor_roles, request_id) VALUES (CAST(:a AS uuid), CAST(:r AS uuid), :et, :eid, "
      ":act, CAST(:ch AS jsonb), :reason, :ph, :rs, CAST(:u AS uuid), :un, :roles, :rid)",
      a=str(ev["audit_id"]), r=ev.get("report_id"), et=ev["entity_type"], eid=None if ev.get("entity_id") is None else str(ev["entity_id"]),
      act=ev["action"], ch=json.dumps(ev.get("changes") or {}, ensure_ascii=False, default=str), reason=ev.get("reason"),
      ph=ev.get("audit_phase"), rs=ev.get("report_status"), u=str(ev["actor_id"]), un=ev.get("actor_username"),
      roles=list(ev.get("actor_roles") or ()), rid=ev.get("request_id"))


def change_events(audit_id):
    return q("SELECT id, report_id::text, entity_type, entity_id, action, changes, reason, audit_phase, report_status, "
             "actor_id::text, actor_username, actor_roles, created_at FROM engagement.change_events "
             "WHERE audit_id = CAST(:a AS uuid) ORDER BY id", a=str(audit_id))


def audit_report_transitions(audit_id):
    return q("SELECT t.id, t.report_id::text, r.kind, t.report_version, t.action, t.from_status, t.to_status, t.body_sha256, "
             "t.actor_id::text AS actor_id, t.actor_username, t.actor_roles, t.comment, t.created_at, "
             "t.delegation_id::text AS delegation_id, ob.full_name AS on_behalf_of "
             "FROM engagement.report_transitions t JOIN engagement.reports r ON r.id = t.report_id "
             "LEFT JOIN iam.users ob ON ob.id = t.on_behalf_of "
             "WHERE r.audit_id = CAST(:a AS uuid) ORDER BY t.id", a=str(audit_id))


# ------------------------------------------------------------------ puntos de devolución
RP_SQL = ("SELECT p.id, p.report_id::text, p.transition_id, p.target_type, p.target_id, p.target_label, p.description, p.status, "
          "p.created_at, c.username AS created_by_name, p.attended_at, p.attended_note, a.username AS attended_by_name "
          "FROM engagement.review_points p LEFT JOIN iam.users c ON c.id = p.created_by LEFT JOIN iam.users a ON a.id = p.attended_by ")


def review_points(rid):
    return q(RP_SQL + "WHERE p.report_id = CAST(:r AS uuid) ORDER BY p.id", r=str(rid))


def get_review_point(pid):
    return q1(RP_SQL + "WHERE p.id = :i", i=int(pid))


def attend_review_point(pid, user, note):
    """Marca el punto como atendido solo si sigue pendiente; devuelve False si otro lo atendió antes."""
    row = x("UPDATE engagement.review_points SET status = 'ATENDIDO', attended_by = CAST(:u AS uuid), attended_at = clock_timestamp(), "
            "attended_note = :n WHERE id = :i AND status = 'PENDIENTE' RETURNING id", i=int(pid), u=user, n=note).first()
    if row is None:
        db.session.rollback()
        return False
    return True


class StaleReportState(Exception):
    """El informe cambió de estado o de contenido entre la validación y la escritura."""


def transition_report(rid, *, expected_status, expected_sha256, status, action, actor, report_version,
                      actor_username=None, actor_roles=(), comment=None, comment_kind=None,
                      signed_doc=None, phase_snapshot=None, review_points=(), delegation_id=None,
                      on_behalf_of=None, **kw):
    """Cambia el estado del informe con compare-and-set y registra la transición.

    El UPDATE solo se aplica si el informe sigue en `expected_status` con el contenido
    `expected_sha256` que se validó; si no, se revierte todo y se lanza StaleReportState.
    El comentario, el documento firmado, la instantánea y la fila de report_transitions
    se confirman en la misma transacción que el cambio de estado.
    """
    sets = ["status = :s", "updated_at = now()"]
    params = {"s": status, "i": str(rid), "expected": expected_status, "sha": expected_sha256}
    allowed = {
        "submitted_at", "approved_by", "approved_at", "approved_body_sha256",
        "sent_to", "sent_at", "sent_by",
        "jefe_approved_by", "jefe_approved_at", "jefe_approved_body_sha256",
        "gerente_approved_by", "gerente_approved_at", "gerente_approved_body_sha256",
        "contralor_approved_by", "contralor_approved_at", "contralor_approved_body_sha256",
    }
    uuid_cols = {
        "approved_by", "sent_by",
        "jefe_approved_by", "gerente_approved_by", "contralor_approved_by",
    }
    for col, val in kw.items():
        assert col in allowed, f"Columna no permitida: {col}"
        if val == "now":
            sets.append(f"{col} = now()")
        else:
            expression = f"CAST(:{col} AS uuid)" if col in uuid_cols else f":{col}"
            sets.append(f"{col} = {expression}")
            params[col] = val
    updated = x(
        "UPDATE engagement.reports SET " + ", ".join(sets)
        + " WHERE id = CAST(:i AS uuid) AND status = :expected AND body_sha256 = :sha RETURNING id",
        **params,
    ).first()
    if updated is None:
        db.session.rollback()
        raise StaleReportState("El informe cambió de estado o de contenido; recargue e intente de nuevo")
    try:
        if comment_kind:
            _insert_comment(rid, actor, comment_kind, comment)
        if signed_doc:
            _insert_signed_doc(rid, user=actor, **signed_doc)
        transition_id = x(
            "INSERT INTO engagement.report_transitions "
            "(report_id, report_version, action, from_status, to_status, body_sha256, "
            "actor_id, actor_username, actor_roles, comment, delegation_id, on_behalf_of) "
            "VALUES (CAST(:r AS uuid), :v, :action, :f, :t, :h, CAST(:u AS uuid), :un, :roles, :c, "
            "CAST(:dg AS uuid), CAST(:ob AS uuid)) RETURNING id",
            r=str(rid), v=report_version, action=action, f=expected_status, t=status,
            h=expected_sha256, u=actor, un=actor_username, roles=list(actor_roles or ()), c=comment,
            dg=delegation_id, ob=on_behalf_of,
        ).scalar_one()
        for point in review_points or ():
            x("INSERT INTO engagement.review_points (report_id, transition_id, target_type, target_id, target_label, description, created_by) "
              "VALUES (CAST(:r AS uuid), :t, :tt, :tid, :tl, :d, CAST(:u AS uuid))",
              r=str(rid), t=transition_id, tt=point["target_type"], tid=point.get("target_id"),
              tl=point.get("target_label"), d=point["description"], u=actor)
        if phase_snapshot:
            _insert_phase_score_snapshot(phase_snapshot)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def report_transitions(rid):
    return q("SELECT t.id, t.report_version, t.action, t.from_status, t.to_status, t.body_sha256, "
             "t.actor_id::text AS actor_id, t.actor_username, t.actor_roles, t.comment, t.created_at, "
             "t.delegation_id::text AS delegation_id, ob.full_name AS on_behalf_of "
             "FROM engagement.report_transitions t LEFT JOIN iam.users ob ON ob.id = t.on_behalf_of "
             "WHERE t.report_id = CAST(:r AS uuid) ORDER BY t.id", r=str(rid))


def _insert_comment(rid, user, kind, text_):
    x("INSERT INTO engagement.report_comments (report_id, author, kind, text) VALUES (CAST(:r AS uuid), CAST(:u AS uuid), :k, :t)", r=str(rid), u=user, k=kind, t=text_)


def add_comment(rid, user, kind, text_):
    _insert_comment(rid, user, kind, text_)
    db.session.commit()


def comments(rid):
    return q("SELECT c.kind, c.text, c.created_at, u.username, u.full_name FROM engagement.report_comments c JOIN iam.users u ON u.id = c.author "
             "WHERE c.report_id = CAST(:r AS uuid) ORDER BY c.id", r=str(rid))


def add_signoff(rid, signer_type, user_id, display, sha, physical=False, note=None):
    x("INSERT INTO engagement.signoffs (report_id, signer_type, user_id, display, body_sha256, physical, note) VALUES (CAST(:r AS uuid), :t, CAST(:u AS uuid), :d, :h, :p, :n) "
      "ON CONFLICT DO NOTHING", r=str(rid), t=signer_type, u=user_id, d=display, h=sha, p=physical, n=note)
    db.session.commit()


def signoffs(rid):
    return q("SELECT signer_type, user_id::text, display, body_sha256, signed_at, physical, note FROM engagement.signoffs WHERE report_id = CAST(:r AS uuid) ORDER BY id", r=str(rid))


def _insert_signed_doc(rid, *, role, version, signed, key, user):
    x("INSERT INTO engagement.signed_documents (id, report_id, signer_role, version, sha256_unsigned, sha256_signed, object_key, signer_user_id, signer_subject, cert_serial, cert_sha256, signed_at, tsa_url, timestamp_embedded) "
      "VALUES (CAST(:i AS uuid), CAST(:r AS uuid), :ro, :v, :hu, :hs, :k, CAST(:u AS uuid), :sub, :ser, :cs, :at, :tsa, :ts)",
      i=str(uuid.uuid4()), r=str(rid), ro=role, v=version, hu=signed.sha256_unsigned, hs=signed.sha256_signed, k=key, u=user, sub=signed.signer_subject,
      ser=signed.cert_serial, cs=signed.cert_sha256, at=signed.signed_at, tsa=signed.tsa_url, ts=signed.timestamp_embedded)


def signed_docs(rid):
    return q("SELECT signer_role, version, sha256_signed, object_key, signer_subject, signed_at, timestamp_embedded, signer_user_id::text AS user_id "
             "FROM engagement.signed_documents WHERE report_id = CAST(:r AS uuid) ORDER BY version", r=str(rid))


def mark_pac_sent(audit_id, to, user, phase_snapshot=None):
    x("UPDATE engagement.audits SET pac_sent_at = now(), pac_sent_to = :t, pac_sent_by = CAST(:u AS uuid), status = 'CLOSED' WHERE id = CAST(:a AS uuid)", t=to, u=user, a=str(audit_id))
    x("UPDATE engagement.files SET status = 'CLOSED' WHERE id = (SELECT file_id FROM engagement.audits WHERE id = CAST(:a AS uuid)) "
      "AND NOT EXISTS (SELECT 1 FROM engagement.audits o WHERE o.file_id = engagement.files.id AND o.status NOT IN ('CLOSED', 'ANULADA'))", a=str(audit_id))
    if phase_snapshot:
        _insert_phase_score_snapshot(phase_snapshot)
    db.session.commit()


def thresholds():
    r = q1("SELECT value FROM admin.system_params WHERE key = 'rating_thresholds'")
    return r["value"] if r else None


def company():
    r = q1("SELECT value FROM admin.system_params WHERE key = 'company_name'")
    return r["value"] if r else None


def apply_offline(plan, criteria_by_ws, user):
    """Aplica filas UPDATE/NEW de un paquete sin conexión en UNA transacción (todo o nada)."""
    from . import scoring
    done = 0
    try:
        for p in plan:
            if p["status"] not in ("UPDATE", "NEW"):
                continue
            d, crit = p["data"], criteria_by_ws[p["worksheet_id"]]
            auto = scoring.item_score(crit, d["results"])
            iid = p["item_id"]
            if p["status"] == "NEW":
                iid = str(uuid.uuid4())
                x("INSERT INTO engagement.items (id, worksheet_id, ref, source, updated_by) VALUES (CAST(:i AS uuid), CAST(:w AS uuid), :r, 'OFFLINE', CAST(:u AS uuid))",
                  i=iid, w=p["worksheet_id"], r=p["ref"], u=user)
            x("UPDATE engagement.items SET results = CAST(:r AS jsonb), observation = :o, info_exception = :e, auto_score = :a, source = 'OFFLINE', "
              "manual_score = :ms, manual_reason = :mr, manual_by = CASE WHEN :ms IS NULL THEN NULL ELSE CAST(:u AS uuid) END, "
              "manual_at = CASE WHEN :ms IS NULL THEN NULL ELSE now() END, updated_by = CAST(:u AS uuid), updated_at = now() WHERE id = CAST(:i AS uuid)",
              r=json.dumps(d["results"]), o=d["obs"] or None, e=d["exc"] or None, a=auto, ms=d["manual"], mr=d["reason"] or None, u=user, i=iid)
            x("UPDATE engagement.worksheets SET updated_at = now() WHERE id = CAST(:w AS uuid)", w=p["worksheet_id"])
            done += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return done


# ------------------------------------------------------------------ suplencias temporales
DELEGATION_SQL = (
    "SELECT d.id::text, d.stage, d.audit_domain, d.titular_id::text, t.full_name AS titular_name, "
    "d.delegate_id::text, s.full_name AS delegate_name, d.starts_on, d.ends_on, d.reason, "
    "d.authorized_by::text, a.full_name AS authorized_by_name, d.created_at, d.revoked_at, d.revoke_reason, "
    "(d.revoked_at IS NULL AND current_date BETWEEN d.starts_on AND d.ends_on) AS active "
    "FROM engagement.delegations d JOIN iam.users t ON t.id = d.titular_id JOIN iam.users s ON s.id = d.delegate_id "
    "JOIN iam.users a ON a.id = d.authorized_by "
)


def active_delegations(user_id):
    """Suplencias vigentes hoy en las que el usuario es el suplente (con cuenta activa)."""
    return q(DELEGATION_SQL + "WHERE d.delegate_id = CAST(:u AS uuid) AND d.revoked_at IS NULL "
             "AND current_date BETWEEN d.starts_on AND d.ends_on AND s.is_active ORDER BY d.created_at", u=str(user_id))


def list_delegations(user_id=None, include_past=False):
    where = ["TRUE"]
    if user_id:
        where.append("(d.delegate_id = CAST(:u AS uuid) OR d.titular_id = CAST(:u AS uuid) OR d.authorized_by = CAST(:u AS uuid))")
    if not include_past:
        where.append("d.revoked_at IS NULL AND d.ends_on >= current_date")
    return q(DELEGATION_SQL + "WHERE " + " AND ".join(where) + " ORDER BY d.starts_on DESC, d.created_at DESC LIMIT 200",
             u=str(user_id) if user_id else None)


def get_delegation(did):
    return q1(DELEGATION_SQL + "WHERE d.id = CAST(:i AS uuid)", i=str(did))


def overlapping_delegation(stage, domain, titular_id, starts_on, ends_on):
    return q1("SELECT id::text FROM engagement.delegations WHERE stage = :s AND audit_domain IS NOT DISTINCT FROM :d "
              "AND titular_id = CAST(:t AS uuid) AND revoked_at IS NULL AND starts_on <= :e AND ends_on >= :b",
              s=stage, d=domain, t=str(titular_id), b=starts_on, e=ends_on)


def create_delegation(d, authorized_by):
    did = str(uuid.uuid4())
    x("INSERT INTO engagement.delegations (id, stage, audit_domain, titular_id, delegate_id, starts_on, ends_on, reason, authorized_by) "
      "VALUES (CAST(:i AS uuid), :s, :d, CAST(:t AS uuid), CAST(:g AS uuid), :b, :e, :r, CAST(:a AS uuid))",
      i=did, s=d["stage"], d=d.get("audit_domain"), t=d["titular_id"], g=d["delegate_id"], b=d["starts_on"],
      e=d["ends_on"], r=d["reason"], a=str(authorized_by))
    db.session.commit()
    return did


def revoke_delegation(did, user, reason):
    row = x("UPDATE engagement.delegations SET revoked_at = now(), revoked_by = CAST(:u AS uuid), revoke_reason = :r "
            "WHERE id = CAST(:i AS uuid) AND revoked_at IS NULL RETURNING id", i=str(did), u=str(user), r=reason).first()
    db.session.commit()
    return row is not None


def user_brief(user_id):
    return q1("SELECT u.id::text, u.username, u.full_name AS name, u.is_active, u.removed_at, "
              "COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') AS roles FROM iam.users u "
              "LEFT JOIN iam.user_roles ur ON ur.user_id = u.id LEFT JOIN iam.roles r ON r.id = ur.role_id "
              "WHERE u.id = CAST(:u AS uuid) GROUP BY u.id", u=str(user_id))


def delegation_candidates():
    """Cuentas activas con sus roles, para elegir titular y suplente."""
    return q("SELECT u.id::text, u.username, u.full_name AS name, "
             "COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') AS roles FROM iam.users u "
             "LEFT JOIN iam.user_roles ur ON ur.user_id = u.id LEFT JOIN iam.roles r ON r.id = ur.role_id "
             "WHERE u.is_active AND u.removed_at IS NULL GROUP BY u.id ORDER BY u.full_name")


def save_signing_certificate(user_id, p12_encrypted, passphrase_encrypted, info):
    x("INSERT INTO engagement.signing_certificates (user_id, p12_encrypted, passphrase_encrypted, subject, serial, not_after) "
      "VALUES (CAST(:u AS uuid), :p, :k, :s, :n, :a) ON CONFLICT (user_id) DO UPDATE SET p12_encrypted = EXCLUDED.p12_encrypted, "
      "passphrase_encrypted = EXCLUDED.passphrase_encrypted, subject = EXCLUDED.subject, serial = EXCLUDED.serial, "
      "not_after = EXCLUDED.not_after, uploaded_at = now()",
      u=str(user_id), p=p12_encrypted, k=passphrase_encrypted, s=info.get("subject"), n=info.get("serial"), a=info.get("not_after"))
    db.session.commit()


def signing_certificate(user_id):
    return q1("SELECT user_id::text, p12_encrypted, passphrase_encrypted, subject, serial, not_after, uploaded_at "
              "FROM engagement.signing_certificates WHERE user_id = CAST(:u AS uuid)", u=str(user_id))


# ------------------------------------------------------------------ firmas escaneadas
def active_signature(user_id, kind="COMPLETA"):
    """Firma escaneada vigente del usuario (PNG), o None. Los auditores del equipo solo estampan iniciales."""
    r = q1("SELECT s.id::text, s.content, s.sha256, u.full_name FROM engagement.signature_assets s JOIN iam.users u ON u.id = s.user_id "
           "WHERE s.user_id = CAST(:u AS uuid) AND s.signature_type = :t AND s.active AND u.removed_at IS NULL",
           u=str(user_id), t=kind)
    if r:
        r["content"] = bytes(r["content"])
    return r
