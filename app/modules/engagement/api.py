"""API de auditorías: expedientes, fases, cédulas, observaciones, evidencias, trabajo sin conexión, informes, PAC y firmas."""
import hashlib
import io
import re
import uuid
from datetime import date, datetime, timezone

from flask import Blueprint, Response, current_app, g, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.core.audit.audit_service import audit as log
from app.core.security.rbac import permission_required

from . import assemble as asm
from . import evidence_rules, offline, scoring, storage, system_questionnaire
from . import repositories as repo
from . import workflow as wf
from .pac import build_pac
from .report_builder import SIG_BOX_CONTRALOR, SIG_BOX_GERENTE, body_hash, build_pdf, initials_of
from .templates import BRANCH_TO_LINE, KINDS, LINES, TEMPLATE_KEYS, branches_for_line, validate_criteria
from app.modules.notifications.service import (
    notify_report_submitted, notify_report_jefe_approved, notify_report_returned, notify_report_signed,
)

bp = Blueprint("engagement", __name__)
EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHASES = ("PLANIFICACION", "TRABAJO_CAMPO", "INFORME")
LOCKING = ("IN_REVIEW", "APPROVED", "SIGNED")


def err(msg, code=400):
    return jsonify(error=msg), code


def me():
    return get_jwt_identity()


def perms():
    return set(g.claims.get("perms", []))


def txt(d, key, lo=0, hi=2000):
    v = str(d.get(key) or "").strip()
    if len(v) < lo or len(v) > hi:
        raise ValueError(f"{key}: entre {lo} y {hi} caracteres")
    return v or None


def parse_date(v, name, required=False):
    if not v:
        if required:
            raise ValueError(f"{name}: fecha obligatoria")
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValueError(f"{name}: fecha inválida (AAAA-MM-DD)")




def audit_domains():
    p = perms()
    if "audit:report_approve" in p or "audit:sign_gerente" in p:
        return {"ALL"}
    d = set()
    if "audit:financial_read" in p or "audit:financial_manage" in p or "audit:financial_review" in p:
        d.add("FINANCIERA")
    if "audit:systems_read" in p or "audit:systems_manage" in p or "audit:systems_review" in p:
        d.add("SISTEMAS")
    if not d and "audit:manage" in p:
        d.add("GENERAL")
    return d


def allowed_domain(domain):
    return "ALL" in audit_domains() or domain in audit_domains()


def can_review_domain(domain):
    p = perms()
    return (
        (domain == "FINANCIERA" and "audit:financial_review" in p)
        or (domain == "SISTEMAS" and "audit:systems_review" in p)
        or "audit:report_approve" in p
    )


def visible(a) -> bool:
    return allowed_domain(a.get("audit_domain", "GENERAL")) and (
        "audit:report_approve" in perms()
        or "audit:sign_gerente" in perms()
        or can_review_domain(a.get("audit_domain", "GENERAL"))
        or repo.is_member(a["id"], me())
    )


def load(aid, write=False, phases=None):
    """(auditoría, error). write=True exige ser del equipo, auditoría en curso, fase válida y sin informe en revisión/aprobado/firmado."""
    a = repo.get_audit(aid)
    if a is None or not visible(a):
        return None, err("No encontrada", 404)
    if write:
        if not repo.is_member(a["id"], me()):
            return None, err("Solo el equipo auditor puede modificar esta auditoría", 403)
        if a["status"] != "IN_PROGRESS":
            return None, err("La auditoría está cerrada", 409)
        if phases and a["phase"] not in phases:
            return None, err("No disponible en la fase actual (" + a["phase"] + ")", 409)
        if any(r["kind"] == "FINAL" and r["status"] in LOCKING for r in repo.reports(a["id"])):
            return None, err("El informe final está en revisión, aprobado o firmado: la información quedó bloqueada", 409)
    return a, None


def thresholds():
    return repo.thresholds() or scoring.DEFAULT_THRESHOLDS


# ------------------------------------------------------------------ catálogos y expedientes
@bp.get("/units")
@permission_required("audit:read", "audit:manage")
def units():
    return jsonify(units=repo.list_units(domains=sorted(audit_domains())))


@bp.post("/units")
@permission_required("audit:unit_manage")
def new_unit():
    d = request.get_json(silent=True) or {}
    code, name, kind = str(d.get("code", "")).strip().upper(), str(d.get("name", "")).strip(), str(d.get("kind", "")).upper()
    if not re.fullmatch(r"[A-Z0-9-]{2,20}", code) or not 3 <= len(name) <= 120 or kind not in ("SUCURSAL", "UNIDAD"):
        return err("Código (2-20 letras/números), nombre (3-120) y tipo (SUCURSAL o UNIDAD) son obligatorios")
    try:
        uid_ = repo.create_unit(code, name, kind)
    except Exception:  # noqa: BLE001 - código duplicado
        repo.db.session.rollback()
        return err("Ya existe una unidad con ese código", 409)
    log("UNIT_CREATED", entity_type="unit", entity_id=str(uid_), after_data={"code": code}, request_id=g.request_id)
    return jsonify(id=uid_), 201


@bp.get("/files")
@permission_required("audit:read")
def files():
    return jsonify(files=repo.list_files(sorted(audit_domains())))


@bp.post("/files")
@permission_required("audit:manage")
def new_file():
    d = request.get_json(silent=True) or {}

    try:
        title = txt(d, "title", 5, 200)
        objective = txt(d, "objective", 0, 2000)
        pf = parse_date(d.get("period_from"), "Período desde", True)
        pt = parse_date(d.get("period_to"), "Período hasta", True)
        unit_id = int(d.get("unit_id"))
    except ValueError as e:
        return err(str(e))
    except TypeError:
        return err("Seleccione la unidad auditada")

    if pt < pf:
        return err("El período final no puede ser anterior al inicial")

    domain = (
        next(iter(audit_domains()))
        if audit_domains() != {"ALL"}
        else "GENERAL"
    )

    unit = repo.get_unit(unit_id)

    if unit is None or not unit["active"]:
        return err("Unidad inexistente o inactiva")

    unit_domain = str(unit.get("audit_domain") or "GENERAL").upper()

    if domain == "FINANCIERA":
        if unit_domain not in ("GENERAL", "FINANCIERA"):
            return err(
                "La unidad seleccionada no pertenece al dominio de auditoría financiera de su rol",
                403,
            )

    elif domain == "SISTEMAS":
        if unit_domain != "SISTEMAS":
            return err(
                "La unidad seleccionada no pertenece al dominio de auditoría de sistemas de su rol",
                403,
            )

    elif domain == "GENERAL":
        if unit_domain != "GENERAL":
            return err(
                "Una auditoría operacional no puede utilizar una unidad reservada a Sistemas/Finanzas",
                403,
            )

    code = repo.next_code("EXP", "file_seq", date.today().year)
    fid = repo.create_file(
        code,
        unit_id,
        title,
        objective,
        pf,
        pt,
        me(),
        domain,
    )

    log(
        "FILE_CREATED",
        entity_type="file",
        entity_id=fid,
        after_data={"code": code},
        request_id=g.request_id,
    )

    return jsonify(id=fid, code=code), 201



# ------------------------------------------------------------------ auditorías
@bp.get("/auditors")
@permission_required("audit:manage")
def auditors():
    domain = next(iter(audit_domains())) if audit_domains() != {"ALL"} else "GENERAL"
    return jsonify(auditors=repo.eligible_auditors(domain))


@bp.get("")
@permission_required("audit:read")
def list_audits():
    mine = repo.my_audit_ids(me())
    p = perms()
    allv = "audit:report_approve" in p or "audit:sign_gerente" in p or "audit:financial_review" in p or "audit:systems_review" in p
    rows = [a for a in repo.list_audits(domains=sorted(audit_domains())) if allv or a["id"] in mine]
    return jsonify(audits=rows)


@bp.post("")
@permission_required("audit:manage")
def new_audit():
    d = request.get_json(silent=True) or {}
    try:
        f = repo.get_file(d.get("file_id"))
        if f is None or f["status"] != "OPEN":
            return err("Primero cree el expediente (el expediente debe existir y estar abierto)")
        modality = str(d.get("modality", "")).upper()
        if modality not in ("REMOTA", "PRESENCIAL"):
            return err("Modalidad: REMOTA o PRESENCIAL")
        domain = str(f.get("audit_domain") or "GENERAL")
        if not allowed_domain(domain):
            return err("El expediente está fuera del alcance de su rol", 403)
        if domain == "SISTEMAS":
            lines = ["ERP_TI"]
            contact_name = str(d.get("contact_name") or f.get("responsible_name") or "").strip()
            contact_role = str(d.get("contact_role") or f.get("responsible_role") or "").strip()
        else:
            lines = [l for l in d.get("lines", []) if l in LINES and l != "ERP_TI"]
            if not lines:
                return err("Seleccione al menos una línea (Auto, Patrimonial o Personal)")
            contact_name = txt(d, "contact_name", 0, 120)
            contact_role = txt(d, "contact_role", 0, 120)
        if len(contact_name) > 120 or len(contact_role) > 120:
            return err("Responsable de la unidad y cargo: máximo 120 caracteres")
        data = {"modality": modality, "audit_domain": domain, "lines": sorted(set(lines)), "objectives": txt(d, "objectives", 10, 3000), "scope": txt(d, "scope", 10, 3000),
                "procedures": txt(d, "procedures", 0, 3000), "location": txt(d, "location", 0, 200),
                "contact_name": contact_name or None, "contact_role": contact_role or None,
                "planned_start": parse_date(d.get("planned_start"), "Inicio previsto"), "planned_end": parse_date(d.get("planned_end"), "Fin previsto")}
    except ValueError as e:
        return err(str(e))
    if modality == "PRESENCIAL" and not data["location"]:
        return err("En una auditoría presencial indique el lugar")
    if data["planned_start"] and data["planned_end"] and data["planned_end"] < data["planned_start"]:
        return err("La fecha de fin no puede ser anterior a la de inicio")
    eligible = {a["id"]: a for a in repo.eligible_auditors(domain)}
    leader, members = str(d.get("leader_id", "")), [str(m) for m in d.get("member_ids", [])]
    ids = list(dict.fromkeys([leader, *members]))
    if leader not in eligible or any(i not in eligible for i in ids):
        return err("El líder y los miembros deben ser auditores activos")
    if me() not in ids:
        return err("Usted debe formar parte del equipo que crea la auditoría")
    team = [{"user_id": i, "role": "LIDER" if i == leader else "AUDITOR", "initials": initials_of(eligible[i]["name"])} for i in ids]
    code = repo.next_code("AUD", "audit_seq", date.today().year)
    aid = repo.create_audit(code, f["id"], data, team, me())
    if domain == "SISTEMAS":
        try:
            repo.system_worksheet(aid, me())
        except Exception:  # noqa: BLE001
            repo.db.session.rollback()
            return err("La auditoría fue creada, pero no fue posible preparar el cuestionario ERP/TI", 500)
    log("AUDIT_CREATED", entity_type="audit", entity_id=aid, after_data={"code": code, "modality": modality, "lines": data["lines"]}, request_id=g.request_id)
    return jsonify(id=aid, code=code), 201


def audit_overview(a):
    sheets = repo.worksheets_with_items(a["id"])
    th = thresholds()
    pairs = asm.summarize_sheets(sheets, th)
    overall = scoring.audit_summary([s for _, s in pairs], a.get("manual_score"), th)
    reps = repo.reports(a["id"])
    obs = repo.observations(a["id"])
    return {"audit": a, "team": repo.team(a["id"]), "phase_log": repo.phase_log(a["id"]), "overall": overall, "thresholds": th,
            "sheets": [{"id": ws["id"], "kind": ws["kind"], "line": ws["line"], "title": ws["title"], "criteria_count": len(ws["criteria"]),
                        "items": s.items, "scored": s.scored, "exceptions": s.exceptions, "auto": s.auto, "final": s.final,
                        "manual_override": s.manual_override, "rating": s.rating,
                        "statistics": scoring.system_statistics(ws["criteria"], ws["items"]) if ws["kind"] == "SISTEMAS" else None} for ws, s in pairs],
            "observations": len(obs), "evidence": len(repo.evidence(a["id"])), "reports": reps,
            "locked": any(r["kind"] == "FINAL" and r["status"] in LOCKING for r in reps),
            "is_member": repo.is_member(a["id"], me())}


@bp.get("/<uuid:aid>")
@permission_required("audit:read")
def audit_detail(aid):
    a, e = load(aid)
    return e or jsonify(audit_overview(a))


@bp.post("/<uuid:aid>/phase")
@permission_required("audit:manage")
def phase(aid):
    a, e = load(aid, write=True)
    if e:
        return e
    d = request.get_json(silent=True) or {}
    to, note = str(d.get("to", "")).upper(), str(d.get("note") or "").strip()[:500]
    cur = PHASES.index(a["phase"])
    if to not in PHASES or abs(PHASES.index(to) - cur) != 1:
        return err("Solo se avanza o retrocede una fase a la vez")
    sheets = repo.worksheets_with_items(a["id"])
    if to == "TRABAJO_CAMPO" and a["phase"] == "PLANIFICACION" and not sheets:
        return err("Para pasar a Trabajo de campo cree al menos una cédula en Planificación")
    if to == "INFORME":
        empty = [ws["title"] for ws in sheets if not any(scoring.item_score(ws["criteria"], i["results"]) is not None for i in ws["items"])]
        if not sheets or empty:
            return err("Para pasar a Informe, cada cédula debe tener al menos un ítem calificado" + (": " + ", ".join(empty) if empty else ""))
    if PHASES.index(to) < cur and not note:
        return err("Para retroceder de fase indique el motivo")
    repo.change_phase(a["id"], a["phase"], to, me(), note)
    log("AUDIT_PHASE_CHANGED", entity_type="audit", entity_id=a["id"], before_data={"phase": a["phase"]}, after_data={"phase": to, "note": note}, request_id=g.request_id)
    return jsonify(phase=to)


@bp.put("/<uuid:aid>/rating")
@permission_required("audit:rate")
def audit_rating(aid):
    a, e = load(aid, write=True, phases=("TRABAJO_CAMPO", "INFORME"))
    if e:
        return e
    d = request.get_json(silent=True) or {}
    if d.get("clear"):
        repo.set_audit_manual(a["id"], None, None, me())
        log("AUDIT_RATING_CLEARED", entity_type="audit", entity_id=a["id"], request_id=g.request_id)
        return jsonify(status="OK")
    try:
        score, reason = scoring.validate_manual(d.get("score"), d.get("reason"))
    except scoring.ScoreError as ex:
        return err(str(ex))
    repo.set_audit_manual(a["id"], score, reason, me())
    log("AUDIT_RATING_OVERRIDDEN", entity_type="audit", entity_id=a["id"], before_data={"manual": a["manual_score"]}, after_data={"manual": score, "reason": reason}, request_id=g.request_id)
    return jsonify(status="OK")


# ------------------------------------------------------------------ plantillas de cédulas
def template_keys_for_current_user():
    p = perms()

    # Contralor y quien administre las plantillas conserva acceso completo.
    if "audit:template_manage" in p or "audit:report_approve" in p:
        return None

    # Auditor/Jefe de Sistemas: exclusivamente la cédula ERP/TI.
    if (
        "audit:systems_read" in p
        or "audit:systems_manage" in p
        or "audit:systems_execute" in p
        or "audit:systems_review" in p
    ):
        return (("SISTEMAS", "ERP_TI"),)

    # Resto de auditores (incluido Finanzas): nunca recibe la cédula de Sistemas.
    return tuple((kind, line) for kind, line in TEMPLATE_KEYS if kind != "SISTEMAS")


@bp.get("/templates")
@permission_required("audit:read", "audit:manage", "audit:template_manage")
def templates():
    return jsonify(templates=repo.list_templates(template_keys_for_current_user()))


@bp.put("/templates/<kind>/<line>")
@permission_required("audit:template_manage", step_up=True)
def save_template(kind, line):
    if kind not in KINDS or line not in LINES:
        return err("Tipo o línea inexistente", 404)
    try:
        crit = validate_criteria((request.get_json(silent=True) or {}).get("criteria"))
    except ValueError as ex:
        return err(str(ex))
    repo.save_template(kind, line, crit, me())
    log("AUDIT_TEMPLATE_UPDATED", entity_type="template", entity_id=f"{kind}/{line}", after_data={"criterios": len(crit)}, request_id=g.request_id)
    return jsonify(status="OK")


# ------------------------------------------------------------------ cédulas e ítems
@bp.post("/<uuid:aid>/worksheets")
@permission_required("audit:manage", "audit:financial_manage")
def new_worksheet(aid):
    a, e = load(
        aid,
        write=True,
        phases=("PLANIFICACION", "TRABAJO_CAMPO"),
    )

    if e:
        return e

    d = request.get_json(silent=True) or {}

    kind = str(
        d.get("kind", "")
    ).upper().strip()

    line = str(
        d.get("line", "")
    ).upper().strip()

    if kind not in KINDS or line not in LINES:
        return err(
            "Tipo o línea inválidos"
        )

    if line not in a["lines"]:
        return err(
            "La línea no pertenece al alcance de la auditoría"
        )

    try:

        # ============================================================
        # FINANCIERA
        # ============================================================
        #
        # Usa exclusivamente:
        #   engagement.financial_templates
        #   engagement.financial_criteria
        #   engagement.financial_worksheets
        #
        # NO utiliza engagement.templates.
        #
        if str(a.get("audit_domain", "")).upper() == "FINANCIERA":

            wid = repo.create_financial_worksheet(
                a["id"],
                kind,
                line,
                me(),
            )

            log(
                "FINANCIAL_WORKSHEET_CREATED",
                entity_type="worksheet",
                entity_id=wid,
                after_data={
                    "kind": kind,
                    "line": line,
                    "audit_domain": "FINANCIERA",
                },
                request_id=g.request_id,
            )

            return jsonify(id=wid), 201


        # ============================================================
        # SISTEMA EXISTENTE
        # ============================================================
        #
        # Este bloque permanece con la lógica anterior.
        # No se modifica la creación de cédulas actuales.
        #
        crit, ver = repo.get_template(
            kind,
            line,
        )

        wid = repo.create_worksheet(
            a["id"],
            kind,
            line,
            crit,
            ver,
            me(),
        )

        log(
            "WORKSHEET_CREATED",
            entity_type="worksheet",
            entity_id=wid,
            after_data={
                "kind": kind,
                "line": line,
                "audit_domain": a.get("audit_domain"),
            },
            request_id=g.request_id,
        )

        return jsonify(id=wid), 201

    except ValueError as ex:
        repo.db.session.rollback()

        return err(
            str(ex),
            400,
        )

    except Exception:
        repo.db.session.rollback()

        return err(
            "No se pudo crear la cédula",
            500,
        )


def ws_for(ws_id, write=False):
    ws = repo.get_worksheet(ws_id)
    if ws is None:
        return None, None, err("No encontrada", 404)
    a, e = load(ws["audit_id"], write=write, phases=("TRABAJO_CAMPO", "INFORME") if write else None)
    return (ws, a, None) if not e else (None, None, e)


@bp.get("/worksheets/<uuid:wid>")
@permission_required("audit:read")
def worksheet(wid):
    ws, a, e = ws_for(wid)
    if e:
        return e
    for it in ws["items"]:
        it["auto_score"] = scoring.item_score(ws["criteria"], it["results"])
        it["final_score"] = scoring.final_score(it["auto_score"], it["manual_score"])
    s = scoring.worksheet_summary(ws["criteria"], ws["items"], ws["manual_score"], thresholds())
    stats = scoring.system_statistics(ws["criteria"], ws["items"]) if ws["kind"] == "SISTEMAS" else None
    return jsonify(worksheet=ws, summary=s.__dict__, statistics=stats, audit={"id": a["id"], "code": a["code"], "phase": a["phase"], "status": a["status"]},
                   editable=repo.is_member(a["id"], me()) and a["status"] == "IN_PROGRESS" and a["phase"] != "PLANIFICACION")

@bp.post("/worksheets/<uuid:wid>/system-questionnaire/import")
@permission_required("audit:manage", "audit:systems_execute")
def import_system_questionnaire(wid):
    """
    Importa la estructura y respuestas de cualquier cuestionario
    Excel de Auditoría de Sistemas.
    """
    ws, a, e = ws_for(wid, write=True)

    if e:
        return e

    if (
        ws["kind"] != "SISTEMAS"
        or str(a.get("audit_domain") or "").upper().strip() != "SISTEMAS"
    ):
        return err(
            "La importación del cuestionario solo está disponible "
            "para Auditoría de Sistemas",
            403,
        )

    f = request.files.get("file")

    if f is None:
        return err("Adjunte el cuestionario Excel")

    filename = str(
        f.filename or ""
    ).strip()

    if not filename:
        return err(
            "El archivo no tiene nombre"
        )

    data = f.read(
        system_questionnaire.MAX_BYTES + 1
    )

    try:
        name, ctype = evidence_rules.check(
            filename,
            data,
        )

        if not name.lower().endswith(".xlsx"):
            return err(
                "El cuestionario debe ser un archivo .xlsx"
            )

        parsed = system_questionnaire.parse(
            data,
            filename=name,
        )

    except (
        ValueError,
        evidence_rules.EvidenceError,
    ) as ex:
        return err(str(ex))

    rows = parsed.get("rows") or []

    if not rows:
        return err(
            "No se encontraron controles en el Excel",
            400,
        )

    # ---------------------------------------------------------
    # Construir la cédula a partir EXACTAMENTE de los controles
    # encontrados en el Excel.
    # ---------------------------------------------------------
    criteria = []

    for row in rows:
        ref = str(
            row.get("ref")
            or row.get("source_id")
            or row.get("control_id")
            or ""
        ).strip()

        question = str(
            row.get("question")
            or ""
        ).strip()

        if not ref:
            return err(
                "Se encontró un control sin ID",
                400,
            )

        if not question:
            return err(
                f"El control {ref} no tiene pregunta de auditoría",
                400,
            )

        criteria.append(
            {
                "code": ref,
                "text": question,
                "weight": 1,
                "source_id": row.get("source_id") or ref,
                "section": row.get("section") or "Sin sección",
                "evaluation_mode": "SYSTEM_EXCEL",
                "source_sheet": row.get("source_sheet"),
                "source_row": row.get("source_row"),
            }
        )

    codes = [
        str(c["code"]).upper()
        for c in criteria
    ]

    if len(codes) != len(set(codes)):
        return err(
            "El Excel contiene IDs de controles duplicados",
            400,
        )

    # ---------------------------------------------------------
    # Crear/reemplazar la estructura de la cédula.
    # ---------------------------------------------------------
    questionnaire_name = str(
        parsed.get("questionnaire_name")
        or name
        or "Cuestionario de Sistemas"
    ).strip()

    title = (
        f"Auditoría de Sistemas — {questionnaire_name}"
    )[:180]

    try:
        repo.replace_system_questionnaire(
            wid,
            criteria,
            me(),
            title=title,
        )
    except ValueError as ex:
        repo.db.session.rollback()
        return err(
            str(ex),
            409,
        )
    except Exception:
        repo.db.session.rollback()
        return err(
            "No se pudo construir la cédula con la estructura del Excel",
            500,
        )

    fresh_after_replace = repo.get_worksheet(
        wid
    )

    if not fresh_after_replace:
        return err(
            "La cédula fue actualizada pero no pudo recuperarse",
            500,
        )

    items = {
        str(item["ref"]).upper(): item
        for item in (
            fresh_after_replace.get("items")
            or []
        )
    }

    # ---------------------------------------------------------
    # Cargar las respuestas que ya trae el Excel.
    # Los valores vacíos permanecen pendientes de completar
    # manualmente desde SICAS.
    # ---------------------------------------------------------
    imported_count = 0

    for row in rows:
        ref = str(
            row.get("ref")
            or row.get("source_id")
            or ""
        ).strip()

        item = items.get(
            ref.upper()
        )

        if item is None:
            return err(
                f"El control {ref} no pudo crearse en la cédula",
                500,
            )

        result = {
            "control": row.get("control"),
            "documental": row.get("documental"),
            "evidencia": row.get("evidencia"),
        }

        try:
            auto = scoring.item_score(
                fresh_after_replace["criteria"],
                {
                    ref: result,
                },
            )
        except Exception:  # noqa: BLE001
            auto = None

        repo.update_system_item(
            item["id"],
            {
                ref: result,
            },
            row.get("observation"),
            None,
            auto,
            me(),
            source="ONLINE",
        )

        imported_count += 1

    # ---------------------------------------------------------
    # Guardar el Excel original como evidencia.
    # ---------------------------------------------------------
    sha = hashlib.sha256(
        data
    ).hexdigest()

    key = (
        f"evidence/"
        f"{a['id']}/"
        f"{uuid.uuid4()}"
    )

    try:
        storage.put(
            key,
            data,
        )

        eid = repo.add_evidence(
            a["id"],
            None,
            None,
            name,
            ctype,
            len(data),
            sha,
            key,
            (
                "Cuestionario de Auditoría de Sistemas "
                "utilizado para cargar la estructura, "
                "respuestas y evidencias de la auditoría"
            ),
            me(),
        )

    except Exception:  # noqa: BLE001
        repo.db.session.rollback()
        return err(
            "El cuestionario fue procesado, pero no fue posible "
            "conservar el Excel como evidencia",
            500,
        )

    # ---------------------------------------------------------
    # Estadísticas de la cédula resultante.
    # ---------------------------------------------------------
    fresh = repo.get_worksheet(
        wid
    )

    stats = scoring.system_statistics(
        fresh["criteria"],
        fresh["items"],
    )

    log(
        "SYSTEM_QUESTIONNAIRE_IMPORTED",
        entity_type="worksheet",
        entity_id=wid,
        after_data={
            "tipo": parsed["questionnaire_type"],
            "nombre": parsed.get("questionnaire_name"),
            "archivo": name,
            "controles": imported_count,
            "hojas": parsed.get("sheets") or [],
            "evidence_id": eid,
            "sha256": sha,
            **stats,
        },
        request_id=g.request_id,
    )

    return jsonify(
        imported=True,
        questionnaire_type=parsed["questionnaire_type"],
        questionnaire_name=parsed.get("questionnaire_name"),
        source_filename=name,
        sheets=parsed.get("sheets") or [],
        controls=imported_count,
        evidence_id=eid,
        sha256=sha,
        statistics=stats,
    )



@bp.post("/worksheets/<uuid:wid>/system-controls")
@permission_required("audit:manage")
def add_system_control(wid):
    ws, a, e = ws_for(wid, write=True)
    if e:
        return e
    if ws["kind"] != "SISTEMAS" or a.get("audit_domain") != "SISTEMAS":
        return err("El control manual solo está disponible para Auditoría de Sistemas", 403)
    d = request.get_json(silent=True) or {}
    text = str(d.get("text") or "").strip()
    section = str(d.get("section") or "Seguridad de TI").strip()
    try:
        weight = int(d.get("weight", 1))
    except (TypeError, ValueError):
        weight = 1
    if not 5 <= len(text) <= 300:
        return err("El texto del control debe tener entre 5 y 300 caracteres")
    if not 1 <= len(section) <= 150:
        return err("La sección del control no es válida")
    if weight not in (1, 2, 3):
        return err("El peso debe ser 1, 2 o 3")
    try:
        code = repo.add_system_control(wid, text, section, weight, me())
    except ValueError as ex:
        return err(str(ex), 409)
    log("SYSTEM_CONTROL_ADDED", entity_type="worksheet", entity_id=wid,
        after_data={"code": code, "section": section, "weight": weight}, request_id=g.request_id)
    return jsonify(code=code), 201


@bp.post("/worksheets/<uuid:wid>/items")
@permission_required("audit:manage")
def add_items(wid):
    ws, a, e = ws_for(wid, write=True)
    if e:
        return e
    refs = [str(r).strip()[:60] for r in (request.get_json(silent=True) or {}).get("refs", []) if str(r).strip()]
    if not refs or len(refs) > 500:
        return err("Indique entre 1 y 500 referencias")
    n = repo.add_items(ws["id"], list(dict.fromkeys(refs)), me())
    log("ITEMS_ADDED", entity_type="worksheet", entity_id=ws["id"], after_data={"agregados": n}, request_id=g.request_id)
    return jsonify(added=n)


@bp.post("/worksheets/<uuid:wid>/sample")
@permission_required("audit:manage")
def sample(wid):
    ws, a, e = ws_for(wid, write=True)
    if e:
        return e
    try:
        n = int((request.get_json(silent=True) or {}).get("n", 0))
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= 200:
        return err("La muestra debe ser de 1 a 200 ítems")
    if ws["kind"] == "SISTEMAS":
        return err("Las auditorías de Sistemas no usan muestreo de pólizas/siniestros; utilice el cuestionario ERP/TI")
    existing = {i["ref"] for i in ws["items"]}
    refs = repo.sample_refs(ws["kind"], ws["line"], branches_for_line(ws["line"]), a["period_from"], a["period_to"], n, existing)
    added = repo.add_items(ws["id"], refs, me())
    log("SAMPLE_DRAWN", entity_type="worksheet", entity_id=ws["id"], after_data={"solicitados": n, "agregados": added}, request_id=g.request_id)
    return jsonify(added=added, note=None if added else "No hay datos cargados para ese período y línea (cargue pólizas/siniestros en Cargas) o ya están todos en la muestra.")


@bp.put("/items/<uuid:iid>")
@permission_required("audit:manage")
def update_item(iid):
    it = repo.get_item(iid)
    if it is None:
        return err("No encontrado", 404)
    ws, a, e = ws_for(it["worksheet_id"], write=True)
    if e:
        return e
    d = request.get_json(silent=True) or {}
    codes = {c["code"] for c in ws["criteria"]}
    raw_results = d.get("results") or {}
    if scoring.is_system_criteria(ws["criteria"]):
        results = {}
        for k, v in raw_results.items():
            if k not in codes or not isinstance(v, dict):
                continue
            control = str(v.get("control", "")).upper()
            doc = str(v.get("documental", "")).upper()
            evidence = str(v.get("evidencia", "")).upper()
            if control in {"SI", "NO", "PARCIAL"} or doc in scoring.SYSTEM_DOC_POINTS or evidence in scoring.SYSTEM_EVIDENCE_POINTS:
                results[k] = {"control": control if control in {"SI", "NO", "PARCIAL"} else "", "documental": doc if doc in scoring.SYSTEM_DOC_POINTS else "", "evidencia": evidence if evidence in scoring.SYSTEM_EVIDENCE_POINTS else ""}
    else:
        valid = set(scoring.POINTS) | {"NO_APLICA", "EXCEPCION"}
        results = {k: v for k, v in raw_results.items() if k in codes and v in valid}
    obs = str(d.get("observation") or "").strip()[:2000] or None
    exc = str(d.get("info_exception") or "").strip()[:2000] or None
    if "EXCEPCION" in results.values() and not exc:
        return err("Marcó EXCEPCION: describa la información no recibida en el campo de excepción")
    repo.update_item(iid, results, obs, exc, scoring.item_score(ws["criteria"], results), me())
    log("ITEM_UPDATED", entity_type="item", entity_id=str(iid), metadata={"ref": it["ref"]}, request_id=g.request_id)
    return jsonify(auto_score=scoring.item_score(ws["criteria"], results))


def _rate(kind_label, entity_id, current, setter, a_id):
    d = request.get_json(silent=True) or {}
    if d.get("clear"):
        setter(None, None)
        log(kind_label + "_RATING_CLEARED", entity_type=kind_label.lower(), entity_id=entity_id, request_id=g.request_id)
        return jsonify(status="OK")
    try:
        score, reason = scoring.validate_manual(d.get("score"), d.get("reason"))
    except scoring.ScoreError as ex:
        return err(str(ex))
    setter(score, reason)
    log(kind_label + "_RATING_OVERRIDDEN", entity_type=kind_label.lower(), entity_id=entity_id,
        before_data={"manual": current}, after_data={"manual": score, "reason": reason}, request_id=g.request_id)
    return jsonify(status="OK")


@bp.put("/items/<uuid:iid>/rating")
@permission_required("audit:rate")
def item_rating(iid):
    it = repo.get_item(iid)
    if it is None:
        return err("No encontrado", 404)
    ws, a, e = ws_for(it["worksheet_id"], write=True)
    return e or _rate("ITEM", str(iid), it["manual_score"], lambda s, r: repo.set_item_manual(iid, s, r, me()), a["id"])


@bp.put("/worksheets/<uuid:wid>/rating")
@permission_required("audit:rate")
def sheet_rating(wid):
    ws, a, e = ws_for(wid, write=True)
    return e or _rate("WORKSHEET", ws["id"], ws["manual_score"], lambda s, r: repo.set_ws_manual(wid, s, r, me()), a["id"])


# ------------------------------------------------------------------ observaciones
def _obs_fields(d, partial=False):
    out = {}
    if not partial or "title" in d: out["title"] = txt(d, "title", 5, 200)
    if not partial or "condition" in d: out["condition"] = txt(d, "condition", 10, 3000)
    for k in ("criteria", "cause", "effect", "recommendation"):
        if k in d: out[k] = txt(d, k, 0, 3000)
    if not partial or "risk" in d:
        if str(d.get("risk", "")).upper() not in ("ALTO", "MEDIO", "BAJO"):
            raise ValueError("Riesgo: ALTO, MEDIO o BAJO")
        out["risk"] = str(d["risk"]).upper()
    return out


@bp.get("/<uuid:aid>/observations")
@permission_required("audit:read")
def observations(aid):
    a, e = load(aid)
    return e or jsonify(observations=repo.observations(a["id"]))


@bp.post("/<uuid:aid>/observations")
@permission_required("audit:manage")
def new_observation(aid):
    a, e = load(aid, write=True, phases=("TRABAJO_CAMPO", "INFORME"))
    if e:
        return e
    d = request.get_json(silent=True) or {}
    try:
        fields = _obs_fields(d)
    except ValueError as ex:
        return err(str(ex))
    # La observación puede ser general (sin item_id), pero si se vincula a un
    # criterio, ese ítem debe existir y pertenecer a esta misma auditoría.
    raw_item_id = d.get("item_id")
    if raw_item_id in (None, ""):
        fields["item_id"] = None
    else:
        try:
            normalized_item_id = str(uuid.UUID(str(raw_item_id)))
        except (TypeError, ValueError, AttributeError):
            return err("El ítem asociado no tiene un identificador válido.", 400)
        item = repo.get_item(normalized_item_id)
        if item is None:
            return err("El ítem asociado no existe.", 404)
        item_ws = repo.get_worksheet(item["worksheet_id"], with_items=False)
        if item_ws is None or str(item_ws.get("audit_id")) != str(a["id"]):
            return err("El ítem asociado debe pertenecer a la misma auditoría.", 400)
        fields["item_id"] = normalized_item_id
    oid, seq = repo.add_observation(a["id"], fields, me())
    log("OBSERVATION_CREATED", entity_type="observation", entity_id=oid, after_data={"seq": seq, "risk": fields["risk"]}, request_id=g.request_id)
    return jsonify(id=oid, seq=seq), 201


@bp.put("/observations/<uuid:oid>")
@permission_required("audit:manage")
def edit_observation(oid):
    o = repo.get_observation(oid)
    if o is None:
        return err("No encontrada", 404)
    a, e = load(o["audit_id"], write=True, phases=("TRABAJO_CAMPO", "INFORME"))
    if e:
        return e
    d = request.get_json(silent=True) or {}
    try:
        upd = _obs_fields(d, partial=True)
        if "unit_decision" in d:
            upd["unit_decision"] = (str(d["unit_decision"]).upper() or None) if d["unit_decision"] else None
            if upd["unit_decision"] not in (None, "ACEPTA", "NO_ACEPTA", "PARCIAL"):
                raise ValueError("Respuesta de la unidad inválida")
        if "unit_response" in d: upd["unit_response"] = txt(d, "unit_response", 0, 3000)
        if "unit_response_at" in d: upd["unit_response_at"] = parse_date(d["unit_response_at"], "Fecha de respuesta")
        for k in ("pac_action", "pac_owner"):
            if k in d: upd[k] = txt(d, k, 0, 1000)
        if "pac_due" in d: upd["pac_due"] = parse_date(d["pac_due"], "Fecha compromiso")
        if "pac_status" in d:
            if d["pac_status"] not in ("PENDIENTE", "EN_CURSO", "CUMPLIDA"):
                raise ValueError("Estatus del PAC inválido")
            upd["pac_status"] = d["pac_status"]
    except ValueError as ex:
        return err(str(ex))
    repo.update_observation(oid, upd)
    log("OBSERVATION_UPDATED", entity_type="observation", entity_id=str(oid), metadata={"campos": sorted(upd)}, request_id=g.request_id)
    return jsonify(status="OK")


# ------------------------------------------------------------------ evidencias
@bp.get("/<uuid:aid>/evidence")
@permission_required("audit:read")
def list_evidence(aid):
    a, e = load(aid)
    return e or jsonify(evidence=repo.evidence(a["id"]))


@bp.post("/<uuid:aid>/evidence")
@permission_required("audit:manage")
def upload_evidence(aid):
    a, e = load(aid, write=True)
    if e:
        return e
    f = request.files.get("file")
    if f is None:
        return err("Adjunte un archivo")
    data = f.read(evidence_rules.MAX_BYTES + 1)
    try:
        name, ctype = evidence_rules.check(f.filename, data)
    except evidence_rules.EvidenceError as ex:
        return err(str(ex))
    sha = hashlib.sha256(data).hexdigest()
    eid_ = str(uuid.uuid4())
    key = f"evidence/{a['id']}/{eid_}"
    storage.put(key, data)
    item_id, obs_id = request.form.get("item_id") or None, request.form.get("observation_id") or None
    eid = repo.add_evidence(a["id"], item_id, obs_id, name, ctype, len(data), sha, key, (request.form.get("description") or "").strip()[:500] or None, me())
    log("EVIDENCE_ADDED", entity_type="evidence", entity_id=eid, after_data={"file": name, "sha256": sha}, request_id=g.request_id)
    return jsonify(id=eid, sha256=sha), 201


@bp.get("/evidence/<uuid:eid>/download")
@permission_required("audit:read")
def download_evidence(eid):
    ev = repo.get_evidence(eid)
    if ev is None:
        return err("No encontrada", 404)
    a, e = load(ev["audit_id"])
    if e:
        return e
    data = storage.get(ev["object_key"])
    if hashlib.sha256(data).hexdigest() != ev["sha256"]:
        log("EVIDENCE_TAMPERED", outcome="FAILURE", entity_type="evidence", entity_id=str(eid), request_id=g.request_id)
        return err("La evidencia almacenada no coincide con su huella registrada", 500)
    log("EVIDENCE_DOWNLOADED", entity_type="evidence", entity_id=str(eid), request_id=g.request_id)
    return Response(data, mimetype=ev["content_type"], headers={"Content-Disposition": f'attachment; filename="{ev["filename"]}"', "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ 1. trabajo sin conexión
def _offline_key() -> bytes:
    return hashlib.sha256(b"sicas-offline|" + current_app.config["SECRET_KEY"].encode()).digest()


@bp.get("/<uuid:aid>/offline-template")
@permission_required("audit:manage")
def offline_template(aid):
    a, e = load(aid, write=True, phases=("TRABAJO_CAMPO", "INFORME"))
    if e:
        return e
    sheets = repo.worksheets_with_items(a["id"])
    if not sheets:
        return err("Cree primero las cédulas de la auditoría")
    data = offline.export_workbook({"id": a["id"], "code": a["code"], "title": a["title"], "unit": a["unit_name"]},
                                   sheets, _offline_key(), datetime.now(timezone.utc), g.claims.get("username", ""))
    log("OFFLINE_EXPORTED", entity_type="audit", entity_id=a["id"], metadata={"cedulas": len(sheets), "items": sum(len(s["items"]) for s in sheets)}, request_id=g.request_id)
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="SICAS_{a["code"]}_sin_conexion.xlsx"'})


@bp.post("/<uuid:aid>/offline-import")
@permission_required("audit:manage")
def offline_import(aid):
    a, e = load(aid, write=True, phases=("TRABAJO_CAMPO", "INFORME"))
    if e:
        return e
    f = request.files.get("file")
    if f is None:
        return err("Adjunte el archivo de Excel descargado de SICAS")
    data = f.read(offline.MAX_BYTES + 1)
    dry = request.form.get("dry_run", "1") != "0"
    overwrite = request.form.get("overwrite") == "1"
    try:
        control, rows, problems = offline.parse_workbook(data, _offline_key(), a["id"])
    except offline.OfflineError as ex:
        log("OFFLINE_IMPORT_REJECTED", outcome="DENIED", entity_type="audit", entity_id=a["id"], metadata={"reason": str(ex)}, request_id=g.request_id)
        return err(str(ex))
    sheets = {ws["id"]: ws for ws in repo.worksheets_with_items(a["id"])}
    if any(m["id"] not in sheets for m in control["sheets"].values()):
        return err("El paquete incluye cédulas que ya no existen en esta auditoría")
    current, refs = {}, {}
    for wid, ws in sheets.items():
        codes = [c["code"] for c in ws["criteria"]]
        refs[wid] = {i["ref"] for i in ws["items"]}
        for i in ws["items"]:
            current[i["id"]] = {"hash": offline.row_hash(i["results"], i["manual_score"], i["manual_reason"], i["observation"], i["info_exception"], codes)}
    plan = offline.plan_changes(control, rows, current, refs, overwrite)
    summary = offline.summarize(plan)
    sha = hashlib.sha256(data).hexdigest()
    if dry:
        return jsonify(dry_run=True, summary=summary, problems=problems, preview=[{k: v for k, v in p.items() if k != "data"} for p in plan if p["status"] != "UNCHANGED"][:300],
                       exported_at=control["exported_at"])
    if summary["INVALID"] or problems:
        return err("El archivo tiene filas inválidas; corríjalas y vuélvalo a cargar (use la vista previa para verlas)")
    done = repo.apply_offline(plan, {wid: ws["criteria"] for wid, ws in sheets.items()}, me())
    log("OFFLINE_IMPORTED", entity_type="audit", entity_id=a["id"], metadata={"archivo_sha256": sha, "aplicadas": done, **summary, "sobrescribir": overwrite}, request_id=g.request_id)
    return jsonify(dry_run=False, applied=done, summary=summary)


# ------------------------------------------------------------------ informes
def _team_info(aid):
    return [{"name": t["name"], "initials": t["initials"], "role": t["role"], "user_id": t["user_id"]} for t in repo.team(aid)]


def _make_body(a, kind, version, conclusion):
    team = _team_info(a["id"])
    return asm.assemble(
        kind=kind, audit=a, file={"code": a["file_code"], "title": a["title"], "period_from": a["period_from"], "period_to": a["period_to"]},
        unit={"code": a["unit_code"], "name": a["unit_name"], "kind": a["unit_kind"]}, team=team,
        worksheets=repo.worksheets_with_items(a["id"]), observations=repo.observations(a["id"]), evidence=repo.evidence(a["id"]),
        thresholds=thresholds(), company=repo.company() or current_app.config["COMPANY_NAME"], version=version, today=date.today(), conclusion=conclusion)


def _state(rep, team):
    sos = repo.signoffs(rep["id"])
    docs = repo.signed_docs(rep["id"])
    return wf.ReportState(
        kind=rep["kind"], status=rep["status"],
        created_by=rep["created_by"], body_sha256=rep["body_sha256"],
        team_ids=[t["user_id"] for t in team],
        initialed_ids={
            s["user_id"] for s in sos
            if s["signer_type"] == "AUDITOR_INICIALES"
            and s["body_sha256"] == rep["body_sha256"]
        },
        jefe_approved_by=rep["jefe_approved_by"],
        jefe_approved_body_sha256=rep["jefe_approved_body_sha256"],
        gerente_approved_by=rep["gerente_approved_by"],
        gerente_approved_body_sha256=rep["gerente_approved_body_sha256"],
        contralor_approved_by=rep["contralor_approved_by"],
        contralor_approved_body_sha256=rep["contralor_approved_body_sha256"],
        approved_by=rep["approved_by"],
        approved_body_sha256=rep["approved_body_sha256"],
        signed_roles={d["signer_role"]: d["user_id"] for d in docs},
    )


def _pdf_for(rep, team):
    sos = repo.signoffs(rep["id"])
    valid = {s["user_id"]: s["display"] for s in sos if s["signer_type"] == "AUDITOR_INICIALES" and s["body_sha256"] == rep["body_sha256"]}
    collab = next(({"name": s["display"].split(" | ")[0], "role": (s["display"].split(" | ") + [""])[1]} for s in reversed(sos) if s["signer_type"] == "COLABORADOR"), None)
    final = rep["kind"] == "FINAL" and rep["status"] in (
        "GERENCIA", "CONTRALOR", "APPROVED", "SIGNED"
    )
    return build_pdf(rep["body"], {"final": final, "initials": {t["name"]: valid.get(t["user_id"]) for t in team}, "collaborator": collab})


def get_rep(rid, write=False, final_viewer=False):
    rep = repo.get_report(rid)
    if rep is None:
        return None, None, None, err("No encontrado", 404)
    a = repo.get_audit(rep["audit_id"])
    pset = perms()
    stage_view = (
        (rep["status"] == "IN_REVIEW" and "audit:report_approve_jefe" in pset)
        or (rep["status"] == "GERENCIA" and "audit:report_approve_gerente" in pset)
        or (rep["status"] == "CONTRALOR" and (
            "audit:report_approve" in pset or "audit:sign_contralor" in pset
        ))
    )
    final_view = (
        rep["status"] in ("CONTRALOR", "APPROVED", "SIGNED")
        and (
            "audit:read_final" in pset
            or "audit:sign_gerente" in pset
            or "audit:sign_contralor" in pset
            or "audit:report_approve" in pset
        )
    )
    if final_viewer and rep["kind"] == "FINAL" and (stage_view or final_view):
        return rep, a, _team_info(a["id"]), None
    if a is None or not visible(a):
        return None, None, None, err("No encontrado", 404)
    if write and not repo.is_member(a["id"], me()):
        return None, None, None, err("Solo el equipo auditor puede realizar esta acción", 403)
    return rep, a, _team_info(a["id"]), None


def try_email(to, subject, body, attachments):
    import os
    import smtplib
    from email.message import EmailMessage
    host = os.environ.get("SMTP_HOST")
    if not host or not EMAIL_RX.match(to or ""):
        return False
    try:
        m = EmailMessage()
        m["Subject"], m["From"], m["To"] = subject, os.environ.get("ALERT_FROM", "contraloria@localhost"), to
        m.set_content(body)
        for name, data, mime in attachments:
            main, sub = mime.split("/")
            m.add_attachment(data, maintype=main, subtype=sub, filename=name)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 25)), timeout=20) as s:
            if os.environ.get("SMTP_STARTTLS") == "1":
                s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(m)
        return True
    except Exception:  # noqa: BLE001
        current_app.logger.exception("No se pudo enviar el correo")
        return False


@bp.get("/<uuid:aid>/reports")
@permission_required("audit:read")
def list_reports(aid):
    a, e = load(aid)
    return e or jsonify(reports=repo.reports(a["id"]))


@bp.post("/<uuid:aid>/reports")
@permission_required("audit:report_draft")
def new_report(aid):
    d = request.get_json(silent=True) or {}
    kind = str(d.get("kind", "")).upper()
    if kind not in ("PREVIO", "FINAL"):
        return err("Tipo de informe: PREVIO o FINAL")
    a, e = load(aid, write=True, phases=("INFORME",) if kind == "FINAL" else ("TRABAJO_CAMPO", "INFORME"))
    if e:
        return e
    existing = [r for r in repo.reports(a["id"]) if r["kind"] == kind]
    if any(r["status"] in ("DRAFT", "RETURNED") for r in existing):
        return err("Ya existe un informe " + kind.lower() + " en borrador; regenere ese en lugar de crear otro", 409)
    try:
        conclusion = txt(d, "conclusion", 0, 4000)
    except ValueError as ex:
        return err(str(ex))
    version = repo.next_version(a["id"], kind)
    body = _make_body(a, kind, version, conclusion)
    rid = repo.create_report(a["id"], kind, version, body, body_hash(body), me())
    log("AUDIT_REPORT_GENERATED", entity_type="audit_report", entity_id=rid, after_data={"kind": kind, "version": version, "sha256": body_hash(body)}, request_id=g.request_id)
    return jsonify(id=rid, version=version), 201


@bp.get("/reports/<uuid:rid>")
@permission_required("audit:read", "audit:read_final")
def report_detail(rid):
    rep, a, team, e = get_rep(rid, final_viewer=True)
    if e:
        return e
    st = _state(rep, team)
    sos, docs = repo.signoffs(rid), repo.signed_docs(rid)
    for dct in docs:
        dct.pop("object_key", None)
    uid_ = me()
    member = uid_ in st.team_ids

    def ok(fn, *args):
        try:
            fn(st, uid_, *args); return True
        except wf.WorkflowError:
            return False
    missing = [t["name"] for t in team if t["user_id"] not in st.initialed_ids]
    pset = perms()
    domain = a.get("audit_domain", "GENERAL")

    jefe_permission = (
        st.status == "IN_REVIEW"
        and "audit:report_approve_jefe" in pset
        and can_review_domain(domain)
    )
    approve_jefe = jefe_permission and ok(wf.can_jefe_review)

    review_permission = (
        jefe_permission
        or (st.status == "GERENCIA" and "audit:report_approve_gerente" in pset)
        or (st.status == "CONTRALOR" and "audit:report_approve" in pset)
    )
    can_return = ok(wf.can_review) and review_permission

    sign_gerente = (
        "audit:sign_gerente" in pset
        and "audit:report_approve_gerente" in pset
        and ok(wf.can_sign, "GERENTE_CI")
    )
    sign_contralor = (
        "audit:sign_contralor" in pset
        and "audit:report_approve" in pset
        and ok(wf.can_sign, "CONTRALOR")
    )

    # Exponer solo la firma más reciente de cada rol si su aprobación
    # corresponde al contenido actual del informe.
    latest_for_role = {}
    for dct in reversed(docs):
        role = dct["signer_role"]
        if role in latest_for_role:
            continue
        approval_hash = (
            st.gerente_approved_body_sha256 if role == "GERENTE_CI"
            else st.contralor_approved_body_sha256 if role == "CONTRALOR"
            else None
        )
        if approval_hash == rep["body_sha256"]:
            latest_for_role[role] = dct
    visible_signatures = list(reversed(list(latest_for_role.values())))

    return jsonify(
        report=rep, team=team, comments=repo.comments(rid),
        signoffs=sos, signatures=visible_signatures,
        missing_initials=missing, is_member=member,
        can={
            "edit": member and ok(wf.can_edit) and "audit:report_draft" in pset,
            "initial": ok(wf.can_initial) and "audit:initial" in pset,
            "submit": ok(wf.can_submit_final) and "audit:report_submit" in pset,
            "send_previo": ok(wf.can_send_previo) and "audit:report_submit" in pset,
            "review": can_return,
            "approve_jefe": approve_jefe,
            "comment": ok(wf.can_comment),
            "sign_contralor": sign_contralor,
            "sign_gerente": sign_gerente,
        },
    )


@bp.post("/reports/<uuid:rid>/regenerate")
@permission_required("audit:report_draft")
def regenerate(rid):
    rep, a, team, e = get_rep(rid, write=True)
    if e:
        return e
    try:
        wf.can_edit(_state(rep, team))
    except wf.WorkflowError as ex:
        return err(str(ex), 409)
    d = request.get_json(silent=True) or {}
    try:
        conclusion = txt(d, "conclusion", 0, 4000) if "conclusion" in d else (rep["body"]["conclusion"] if rep["body"].get("conclusion_custom") else None)
    except ValueError as ex:
        return err(str(ex))
    body = _make_body(a, rep["kind"], rep["version"], conclusion)
    repo.replace_body(rid, body, body_hash(body))
    log("AUDIT_REPORT_REGENERATED", entity_type="audit_report", entity_id=str(rid), after_data={"sha256": body_hash(body)}, request_id=g.request_id)
    return jsonify(status="OK", note="Las iniciales estampadas antes quedan sin efecto: cada auditor debe volver a estamparlas.")


@bp.post("/reports/<uuid:rid>/initial")
@permission_required("audit:initial")
def initial(rid):
    rep, a, team, e = get_rep(rid, write=True)
    if e:
        return e
    try:
        wf.can_initial(_state(rep, team), me())
    except wf.WorkflowError as ex:
        return err(str(ex), 409)
    mine = next(t for t in team if t["user_id"] == me())
    repo.add_signoff(rid, "AUDITOR_INICIALES", me(), mine["initials"], rep["body_sha256"])
    log("REPORT_INITIALED", entity_type="audit_report", entity_id=str(rid), after_data={"initials": mine["initials"], "sha256": rep["body_sha256"]}, request_id=g.request_id)
    return jsonify(initials=mine["initials"])


@bp.post("/reports/<uuid:rid>/collaborator")
@permission_required("audit:manage")
def collaborator(rid):
    rep, a, team, e = get_rep(rid, write=True)
    if e:
        return e
    if repo.signed_docs(rid):
        return err("El informe ya tiene firmas electrónicas; no se puede cambiar", 409)
    d = request.get_json(silent=True) or {}
    try:
        name, role = txt(d, "name", 3, 120), txt(d, "role", 3, 120)
    except ValueError as ex:
        return err(str(ex))
    repo.add_signoff(rid, "COLABORADOR", None, f"{name} | {role}", rep["body_sha256"], physical=bool(d.get("physical")), note=txt(d, "note", 0, 300))
    log("REPORT_COLLABORATOR_RECORDED", entity_type="audit_report", entity_id=str(rid), after_data={"name": name, "role": role}, request_id=g.request_id)
    return jsonify(status="OK")


@bp.post("/reports/<uuid:rid>/submit")
@permission_required("audit:report_submit")
def submit(rid):
    rep, a, team, e = get_rep(rid, write=True)
    if e:
        return e
    try:
        wf.can_submit_final(_state(rep, team), me())
    except wf.WorkflowError as ex:
        return err(str(ex), 409)
    repo.set_report_status(rid, "IN_REVIEW", submitted_at="now")
    log("AUDIT_REPORT_SUBMITTED", entity_type="audit_report", entity_id=str(rid), request_id=g.request_id)
    notify_report_submitted(str(rid), a, str(me()), getattr(g, "request_id", None))
    return jsonify(status="IN_REVIEW")


@bp.post("/reports/<uuid:rid>/send-previo")
@permission_required("audit:report_submit")
def send_previo(rid):
    rep, a, team, e = get_rep(rid, write=True)
    if e:
        return e
    try:
        wf.can_send_previo(_state(rep, team), me())
    except wf.WorkflowError as ex:
        return err(str(ex), 409)
    d = request.get_json(silent=True) or {}
    try:
        to_name = txt(d, "to_name", 3, 150)
    except ValueError as ex:
        return err(str(ex))
    email = str(d.get("to_email") or "").strip()
    if email and not EMAIL_RX.match(email):
        return err("Correo del destinatario inválido")
    if not to_name:
        return err("Indique el destinatario en la unidad")
    emailed = bool(email) and try_email(email, f"Informe previo de auditoría {a['code']}", "Se adjunta el informe previo de auditoría para su revisión y respuesta.",
                                        [(f"{a['code']}_informe_previo.pdf", _pdf_for(rep, team), "application/pdf")])
    repo.set_report_status(rid, "SENT", sent_to=f"{to_name}" + (f" <{email}>" if email else ""), sent_at="now", sent_by=me())
    log("PREVIO_SENT", entity_type="audit_report", entity_id=str(rid), after_data={"to": to_name, "emailed": emailed}, request_id=g.request_id)
    return jsonify(status="SENT", emailed=emailed, note=None if emailed else "Registrado como enviado. Entregue el PDF a la unidad (el correo automático no está configurado o no se indicó correo).")


@bp.post("/reports/<uuid:rid>/comments")
@permission_required("audit:read")
def comment(rid):
    rep, a, team, e = get_rep(rid)
    if e:
        return e
    st = _state(rep, team)
    try:
        wf.can_comment(st, me())
    except wf.WorkflowError as ex:
        return err(str(ex), 409)
    kind = "RESPUESTA" if me() in st.team_ids else ("REVISION" if can_review_domain(a.get("audit_domain", "GENERAL")) else None)
    t = str((request.get_json(silent=True) or {}).get("text") or "").strip()
    if kind is None:
        return err("No participa en la revisión", 403)
    if not 3 <= len(t) <= 3000:
        return err("Escriba el comentario (3 a 3000 caracteres)")
    repo.add_comment(rid, me(), kind, t)
    log("REPORT_COMMENT", entity_type="audit_report", entity_id=str(rid), metadata={"kind": kind}, request_id=g.request_id)
    return jsonify(status="OK"), 201


@bp.post("/reports/<uuid:rid>/return")
@permission_required(
    "audit:report_approve", "audit:financial_review", "audit:systems_review",
    "audit:report_approve_jefe", "audit:report_approve_gerente",
)
def return_report(rid):
    rep, a, team, e = get_rep(rid, final_viewer=True)
    if e:
        return e

    pset = perms()
    stage = rep["status"]

    if stage == "IN_REVIEW":
        if "audit:report_approve_jefe" not in pset or not can_review_domain(a.get("audit_domain", "GENERAL")):
            return err("No tiene permiso para devolver en la etapa del Jefe de Auditoría", 403)
    elif stage == "GERENCIA":
        if "audit:report_approve_gerente" not in pset:
            return err("Solo Gerencia puede devolver el informe en esta etapa", 403)
    elif stage == "CONTRALOR":
        if "audit:report_approve" not in pset:
            return err("Solo el Contralor puede devolver el informe en esta etapa", 403)
    else:
        return err(f"No se puede devolver un informe en estado {stage}", 409)

    try:
        wf.can_review(_state(rep, team), me())
    except wf.WorkflowError as ex:
        return err(str(ex), 409)

    t = str((request.get_json(silent=True) or {}).get("comment") or "").strip()
    if len(t) < 10:
        return err("Indique qué debe corregirse (mínimo 10 caracteres)")

    repo.add_comment(rid, me(), "DEVOLUCION", t)
    # Una devolución invalida las aprobaciones anteriores del contenido.
    # Los PDF firmados históricos se conservan, pero no se presentan como actuales.
    repo.set_report_status(
        rid, "RETURNED",
        approved_by=None, approved_at=None, approved_body_sha256=None,
        jefe_approved_by=None, jefe_approved_at=None, jefe_approved_body_sha256=None,
        gerente_approved_by=None, gerente_approved_at=None, gerente_approved_body_sha256=None,
        contralor_approved_by=None, contralor_approved_at=None, contralor_approved_body_sha256=None,
    )
    log(
        "AUDIT_REPORT_RETURNED", entity_type="audit_report", entity_id=str(rid),
        metadata={"comment": t, "returned_from": stage}, request_id=g.request_id,
    )
    notify_report_returned(str(rid), a, stage, t, str(me()), getattr(g, "request_id", None))
    return jsonify(status="RETURNED")


@bp.post("/reports/<uuid:rid>/approve/jefe")
@permission_required("audit:report_approve_jefe", step_up=True)
def approve_jefe(rid):
    rep, a, team, e = get_rep(rid, final_viewer=True)
    if e:
        return e

    if not can_review_domain(a.get("audit_domain", "GENERAL")):
        return err("No tiene alcance de revisión para esta auditoría", 403)

    try:
        wf.can_jefe_review(_state(rep, team), me())
    except wf.WorkflowError as ex:
        return err(str(ex), 409)

    repo.set_report_status(
        rid, "GERENCIA",
        approved_by=None, approved_at=None, approved_body_sha256=None,
        jefe_approved_by=me(), jefe_approved_at="now",
        jefe_approved_body_sha256=rep["body_sha256"],
    )
    log(
        "AUDIT_REPORT_JEFE_APPROVED", entity_type="audit_report",
        entity_id=str(rid), after_data={"sha256": rep["body_sha256"]},
        request_id=g.request_id,
    )
    notify_report_jefe_approved(str(rid), a, str(me()), getattr(g, "request_id", None))
    return jsonify(
        status="GERENCIA",
        note="Informe aprobado por el Jefe de Auditoría y enviado a Gerencia.",
    )


@bp.post("/reports/<uuid:rid>/approve")
@permission_required("audit:report_approve", step_up=True)
def approve(rid):
    # La aprobación genérica no debe saltarse etapas ni omitir las firmas.
    return err(
        "La aprobación debe realizarse en la etapa correspondiente: "
        "Jefe de Auditoría, firma de Gerencia o firma de Contraloría.",
        409,
    )


def _sign(rid, role):
    from app.modules.reporting.signing import service as signing

    rep, a, team, e = get_rep(rid, final_viewer=True)
    if e:
        return e

    pset = perms()
    if role == "GERENTE_CI":
        if "audit:report_approve_gerente" not in pset:
            return err("Necesita permiso de aprobación de Gerencia además del permiso de firma", 403)
    elif role == "CONTRALOR":
        if "audit:report_approve" not in pset:
            return err("Necesita permiso de aprobación del Contralor además del permiso de firma", 403)
    else:
        return err("Rol de firma inválido", 400)

    st = _state(rep, team)
    try:
        wf.can_sign(st, me(), role)
    except wf.WorkflowError as ex:
        log(
            "AUDIT_REPORT_SIGN_REJECTED", outcome="DENIED",
            entity_type="audit_report", entity_id=str(rid),
            metadata={"role": role, "reason": str(ex)}, request_id=g.request_id,
        )
        return err(str(ex), 409)

    docs = repo.signed_docs(rid)
    version = max((int(d["version"]) for d in docs), default=0) + 1

    if role == "GERENTE_CI":
        # Primera firma: Gerencia firma el PDF final sin firma digital previa.
        base = _pdf_for(rep, team)
        box, field, label = SIG_BOX_GERENTE, "FirmaGerenteCI", "Gerente de Control Interno"
    else:
        # Segunda firma: Contraloría firma encima del PDF firmado por Gerencia.
        manager_doc = next(
            (d for d in reversed(docs) if d["signer_role"] == "GERENTE_CI"),
            None,
        )
        if manager_doc is None:
            return err("Falta la firma digital vigente de Gerencia", 409)
        base = storage.get(manager_doc["object_key"])
        box, field, label = SIG_BOX_CONTRALOR, "FirmaContralor", "Contralor"

    cfg = current_app.config
    try:
        signed = signing.sign_pdf(
            base, signing.load_signer(cfg, role),
            reason=f"Informe de auditoría {a['code']} — {label}",
            location=cfg.get("SIGNING_LOCATION", "Venezuela"),
            signer_name=g.claims.get("username", me()),
            field_name=field, box=box, tsa_url=cfg.get("TSA_URL"),
        )
        key = f"reports/{rid}/v{version}.pdf"
        storage.put(key, signed.pdf_bytes)
    except Exception as ex:  # noqa: BLE001
        log(
            "AUDIT_REPORT_SIGN_FAILED", outcome="FAILURE",
            entity_type="audit_report", entity_id=str(rid),
            metadata={"role": role, "error": type(ex).__name__},
            request_id=g.request_id,
        )
        return err(
            "No fue posible firmar el documento"
            + (f" ({ex})" if cfg.get("ENV") == "dev" else ""),
            500,
        )

    repo.add_signed_doc(rid, role, version, signed, key, me())
    st.signed_roles[role] = me()

    if role == "GERENTE_CI":
        # Aprobar y firmar en una sola transición. El paso siguiente es Contraloría.
        repo.set_report_status(
            rid, "CONTRALOR",
            gerente_approved_by=me(), gerente_approved_at="now",
            gerente_approved_body_sha256=rep["body_sha256"],
        )
        new_status = "CONTRALOR"
    else:
        if not wf.is_fully_signed(st):
            return err("No se pudo confirmar que ambas firmas finales estén registradas", 409)
        repo.set_report_status(
            rid, "SIGNED",
            contralor_approved_by=me(), contralor_approved_at="now",
            contralor_approved_body_sha256=rep["body_sha256"],
            approved_by=me(), approved_at="now",
            approved_body_sha256=rep["body_sha256"],
        )
        new_status = "SIGNED"

    log(
        "AUDIT_REPORT_SIGNED", entity_type="audit_report",
        entity_id=str(rid),
        after_data={
            "role": role, "version": version,
            "sha256_signed": signed.sha256_signed,
            "cert_serial": signed.cert_serial,
        },
        request_id=g.request_id,
    )
    notify_report_signed(str(rid), a, role, new_status, str(me()), getattr(g, "request_id", None))
    return jsonify(
        status=new_status, signed_by=role,
        timestamp_embedded=signed.timestamp_embedded,
    )


@bp.post("/reports/<uuid:rid>/sign/contralor")
@permission_required("audit:sign_contralor", step_up=True)
def sign_contralor(rid):
    return _sign(rid, "CONTRALOR")


@bp.post("/reports/<uuid:rid>/sign/gerente")
@permission_required("audit:sign_gerente", step_up=True)
def sign_gerente(rid):
    return _sign(rid, "GERENTE_CI")


@bp.get("/reports/<uuid:rid>/pdf")
@permission_required("audit:read", "audit:read_final")
def report_pdf(rid):
    rep, a, team, e = get_rep(rid, final_viewer=True)
    if e:
        return e
    docs = repo.signed_docs(rid)
    if rep["kind"] == "FINAL" and rep["status"] in ("CONTRALOR", "SIGNED") and docs:
        latest = docs[-1]
        data = storage.get(latest["object_key"])
        if hashlib.sha256(data).hexdigest() != latest["sha256_signed"]:
            log("SIGNED_DOCUMENT_TAMPERED", outcome="FAILURE", entity_type="audit_report", entity_id=str(rid), request_id=g.request_id)
            return err("El documento almacenado no coincide con su huella registrada", 500)
    else:
        data = _pdf_for(rep, team)
    log("AUDIT_REPORT_PRINTED", entity_type="audit_report", entity_id=str(rid), metadata={"status": rep["status"], "firmado": bool(docs)}, request_id=g.request_id)
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{a["code"]}_{rep["kind"].lower()}_v{rep["version"]}.pdf"',
                                                              "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ PAC (anexo en Excel)
@bp.get("/<uuid:aid>/pac.xlsx")
@permission_required("audit:read")
def pac_file(aid):
    a, e = load(aid)
    if e:
        return e
    data = build_pac({"code": a["code"], "unit": a["unit_name"]}, repo.observations(a["id"]), datetime.now(timezone.utc))
    log("PAC_DOWNLOADED", entity_type="audit", entity_id=a["id"], request_id=g.request_id)
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="PAC_{a["code"]}.xlsx"'})


@bp.post("/<uuid:aid>/pac/send")
@permission_required("audit:pac_send")
def pac_send(aid):
    a, e = load(aid)
    if e:
        return e
    if not repo.is_member(a["id"], me()):
        return err("Solo el equipo auditor envía el PAC", 403)
    if a["status"] != "IN_PROGRESS":
        return err("El PAC ya fue enviado y la auditoría está cerrada", 409)
    finals = [r for r in repo.reports(a["id"]) if r["kind"] == "FINAL"]
    final = next((r for r in finals if r["status"] == "SIGNED"), None)
    try:
        wf.can_send_pac(wf.ReportState("FINAL", final["status"], "", "") if final else None)
    except wf.WorkflowError as ex:
        return err(str(ex), 409)
    d = request.get_json(silent=True) or {}
    to = str(d.get("to") or "").strip()
    if len(to) < 3 or len(to) > 200:
        return err("Indique el destinatario en la unidad (nombre y, si desea envío automático, su correo entre < >)")
    m = re.search(r"[^\s<>]+@[^\s<>]+\.[^\s<>]+", to)
    email = m.group(0) if m else None
    pac = build_pac({"code": a["code"], "unit": a["unit_name"]}, repo.observations(a["id"]), datetime.now(timezone.utc))
    emailed = False
    if email:
        docs = repo.signed_docs(final["id"])
        pdf = storage.get(docs[-1]["object_key"]) if docs else b""
        emailed = try_email(email, f"Informe final y PAC — auditoría {a['code']}", "Se adjuntan el informe final firmado y el Plan de Acción Correctiva (PAC) para su diligenciamiento.",
                            [(f"{a['code']}_informe_final.pdf", pdf, "application/pdf"), (f"PAC_{a['code']}.xlsx", pac, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
    repo.mark_pac_sent(a["id"], to, me())
    log("PAC_SENT", entity_type="audit", entity_id=a["id"], after_data={"to": to, "emailed": emailed}, request_id=g.request_id)
    return jsonify(status="CLOSED", emailed=emailed, note=None if emailed else "Registrado como enviado y auditoría cerrada. Entregue el informe firmado y el PAC a la unidad (el correo automático no está configurado).")


@bp.get("/final-reports")
@permission_required(
    "audit:report_approve", "audit:sign_gerente", "audit:read_final",
    "audit:financial_review", "audit:systems_review",
    "audit:report_approve_jefe", "audit:report_approve_gerente",
)
def final_reports():
    """Bandeja de informes según la etapa de revisión y los permisos del rol."""
    p = perms()
    statuses = {"SIGNED"}

    if "audit:sign_gerente" in p:
        statuses |= {"GERENCIA", "CONTRALOR", "APPROVED", "RETURNED"}
    if "audit:report_approve" in p:
        statuses |= {"IN_REVIEW", "GERENCIA", "CONTRALOR", "APPROVED", "RETURNED"}
    if "audit:report_approve_jefe" in p:
        statuses |= {"IN_REVIEW", "RETURNED"}
    if "audit:report_approve_gerente" in p:
        statuses |= {"GERENCIA", "CONTRALOR", "RETURNED"}
    if "audit:financial_review" in p or "audit:systems_review" in p:
        statuses |= {"IN_REVIEW", "CONTRALOR", "APPROVED", "RETURNED"}

    domains = sorted(audit_domains())
    rows = repo.q(
        "SELECT r.id::text, r.version, r.status, r.submitted_at, r.approved_at, "
        "a.code AS audit_code, a.id::text AS audit_id, f.title, u.name AS unit_name, "
        "(SELECT count(*) FROM engagement.signed_documents s WHERE s.report_id = r.id) AS signatures "
        "FROM engagement.reports r "
        "JOIN engagement.audits a ON a.id = r.audit_id "
        "JOIN engagement.files f ON f.id = a.file_id "
        "JOIN engagement.units u ON u.id = f.unit_id "
        "WHERE r.kind = 'FINAL' AND r.status = ANY(CAST(:s AS text[]))"
        + ("" if "ALL" in domains else " AND a.audit_domain = ANY(CAST(:d AS text[]))")
        + " ORDER BY r.updated_at DESC LIMIT 100",
        s=sorted(statuses), d=domains,
    )

    # Gerencia ve la etapa pendiente de su firma y los documentos que
    # ya tengan una firma registrada; no recibe informes borrador del equipo.
    manager_only = (
        "audit:sign_gerente" in p
        and "audit:report_approve" not in p
        and "audit:financial_review" not in p
        and "audit:systems_review" not in p
        and "audit:report_approve_jefe" not in p
    )
    if manager_only:
        rows = [
            r for r in rows
            if r["status"] in ("GERENCIA", "SIGNED") or r["signatures"] >= 1
        ]

    if "audit:report_approve" not in p:
        rows = [
            r for r in rows
            if can_review_domain(
                repo.get_audit(r["audit_id"]).get("audit_domain", "GENERAL")
            )
            or (
                "audit:sign_gerente" in p
                and (
                    r["status"] in ("GERENCIA", "SIGNED")
                    or r["signatures"] >= 1
                )
            )
            or (
                "audit:report_approve_jefe" in p
                and r["status"] in ("IN_REVIEW", "RETURNED")
            )
            or (
                "audit:report_approve_gerente" in p
                and r["status"] in ("GERENCIA", "CONTRALOR", "RETURNED")
            )
        ]

    return jsonify(reports=rows)
