"""API de auditorías: expedientes, fases, cédulas, observaciones, evidencias, trabajo sin conexión, informes, PAC y firmas."""
import hashlib
import io
import re
import uuid
from datetime import date, datetime, timezone

from flask import Blueprint, Response, current_app, g, jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError

from app.core.audit.audit_service import audit as log
from app.core.security.rbac import permission_required

from . import assemble as asm
from . import codification
from . import score_snapshots
from . import evidence_rules, observation_rules, offline, phase_documents, regulatory_rules, scoring, storage, system_questionnaire
from . import repositories as repo
from . import workflow as wf
from .pac import build_pac
from .report_builder import SIG_BOX_CONTRALOR, SIG_BOX_GERENTE, body_hash, build_pdf, initials_of
from .templates import AUDIT_KINDS, BRANCH_TO_LINE, GENERAL_KINDS, KINDS, LINES, TEMPLATE_KEYS, branches_for_line, validate_criteria
from app.modules.notifications.service import (
    notify_report_submitted, notify_report_jefe_approved, notify_report_returned, notify_report_signed,
)

bp = Blueprint("engagement", __name__)
EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHASES = ("PLANIFICACION", "TRABAJO_CAMPO", "INFORME")
# Auditoría de Sistemas: 1 Levantamiento, 2 Documentación, 3 Pruebas de campo, 4 Informe.
SYSTEM_PHASES = scoring.SYSTEM_PHASES


def is_systems(a) -> bool:
    return str(a.get("audit_domain") or "").upper() == "SISTEMAS"


def phases_for(a):
    return SYSTEM_PHASES if is_systems(a) else PHASES


def phase_group(a, group):
    """Fases en las que se permite cada tipo de trabajo, según el dominio de la auditoría.

    PLAN  : crear cédulas.
    WORK  : observaciones, evidencias, ajustes y trabajo sin conexión.
    ITEMS : responder y calificar los controles de las cédulas.
    """
    if is_systems(a):
        return {"PLAN": SYSTEM_PHASES[:1], "WORK": SYSTEM_PHASES, "ITEMS": scoring.SYSTEM_SCORED_PHASES}[group]
    return {"PLAN": ("PLANIFICACION", "TRABAJO_CAMPO"), "WORK": ("TRABAJO_CAMPO", "INFORME"),
            "ITEMS": ("TRABAJO_CAMPO", "INFORME")}[group]
# Estados del informe final en los que la auditoría queda bloqueada para el equipo.
LOCKING = ("IN_REVIEW", "GERENCIA", "CONTRALOR", "APPROVED", "SIGNED")


def err(msg, code=400):
    return jsonify(error=msg), code


def me():
    return get_jwt_identity()


def own_perms():
    """Permisos del token (roles propios del usuario)."""
    return set(g.claims.get("perms", []))


# ------------------------------------------------------------------ suplencias temporales
# El suplente recibe solo los permisos de la etapa del flujo del informe que cubre; el flujo de
# estados no cambia y cada transición queda registrada "en nombre de" el titular.
STAGE_PERMS = {
    "JEFE": {"audit:read", "report:read", "audit:report_approve_jefe"},
    "GERENCIA": {"audit:read_final", "audit:report_approve_gerente", "audit:sign_gerente"},
    "CONTRALOR": {"audit:read_final", "audit:report_approve", "audit:sign_contralor"},
}
DOMAIN_REVIEW = {
    "FINANCIERA": {"audit:financial_read", "audit:financial_review"},
    "SISTEMAS": {"audit:systems_read", "audit:systems_review"},
}
STAGE_OWN_PERM = {"JEFE": "audit:report_approve_jefe", "GERENCIA": "audit:sign_gerente", "CONTRALOR": "audit:sign_contralor"}
STAGE_AUTHORIZER = {"JEFE": "audit:report_approve", "GERENCIA": "audit:report_approve", "CONTRALOR": "audit:report_approve_gerente"}
STAGE_LABEL = {"JEFE": "Jefe de Auditoría", "GERENCIA": "Gerencia", "CONTRALOR": "Contralor"}
STATUS_STAGE = {"IN_REVIEW": "JEFE", "GERENCIA": "GERENCIA", "CONTRALOR": "CONTRALOR"}
MAX_DELEGATION_DAYS = 90


def stage_perms(stage, domain=None):
    return set(STAGE_PERMS.get(stage, set())) | (DOMAIN_REVIEW.get(domain, set()) if stage == "JEFE" else set())


def sod_conflicts(granted):
    from app.core.security.permissions import SOD_CONFLICTS
    return [c for c in SOD_CONFLICTS if c[0] in granted and c[1] in granted]


def holds_stage(granted, stage, domain=None):
    """El conjunto de permisos ya cubre la etapa (y, para el Jefe, el dominio)."""
    if STAGE_OWN_PERM[stage] not in granted:
        return False
    return stage != "JEFE" or DOMAIN_REVIEW.get(domain, {"-"}) <= granted


def active_delegations():
    """Suplencias vigentes del usuario, una vez por petición. Si la consulta falla no se concede nada (falla cerrada)."""
    cached = getattr(g, "_delegations", None)
    if cached is not None:
        return cached
    rows = []
    try:
        uid = me()
        own = own_perms()
        for d in (repo.active_delegations(uid) if uid else []):
            # Una suplencia que hoy violaría la segregación de funciones (p. ej. por un rol nuevo) no se aplica.
            if not sod_conflicts(own | stage_perms(d["stage"], d.get("audit_domain"))):
                rows.append(d)
    except Exception:  # noqa: BLE001
        try:
            repo.db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        rows = []
    g._delegations = rows
    return rows


def delegated_perms():
    out = set()
    for d in active_delegations():
        out |= stage_perms(d["stage"], d.get("audit_domain"))
    return out


def perms():
    """Permisos efectivos: los propios más los de las suplencias vigentes."""
    return own_perms() | delegated_perms()


def acting_delegation(stage, domain=None):
    """La suplencia con que actúa el usuario en la etapa, o None si la cubre con sus propios roles."""
    if stage is None or holds_stage(own_perms(), stage, domain):
        return None
    return next((d for d in active_delegations()
                 if d["stage"] == stage and (stage != "JEFE" or d.get("audit_domain") == domain)), None)


def stage_required(*needed, step_up=False):
    """Como permission_required, pero acepta también los permisos recibidos por suplencia."""
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            import time

            from flask_jwt_extended import get_jwt, verify_jwt_in_request

            from app.core.security.rbac import _deny
            verify_jwt_in_request()
            claims = get_jwt()
            if not claims.get("mfa"):
                return _deny("MFA requerido")
            g.claims = claims
            if not set(needed) & perms():
                return _deny("Permiso insuficiente")
            if step_up:
                from app.core.security.policy import current as current_policy
                max_age = current_policy()["step_up_seconds"]
                if time.time() - claims.get("mfa_at", 0) > max_age:
                    return jsonify(error="Reautenticación MFA requerida", step_up_required=True), 401
            return fn(*args, **kwargs)
        return wrapper
    return decorator


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
        if isinstance(phases, str):
            phases = phase_group(a, phases)
        if phases and a["phase"] not in phases:
            return None, err("No disponible en la fase actual (" + a["phase"] + ")", 409)
        if final_locked(a["id"]):
            return None, err("El informe final está en revisión, aprobado o firmado: la información quedó bloqueada", 409)
    return a, None


def final_locked(audit_id) -> bool:
    """La auditoría se bloquea según la última versión del informe final.

    Una versión firmada deja de bloquear cuando Contraloría autorizó su reapertura:
    el equipo puede entonces generar la versión siguiente sin alterar la firmada.
    """
    latest = repo.latest_final(audit_id)
    if latest is None or latest["status"] not in LOCKING:
        return False
    return not (latest["status"] == "SIGNED" and repo.reopening(latest["id"]))


def can_edit_data(a) -> bool:
    """Datos generales: los edita el equipo o el Jefe de Auditoría del dominio, con la auditoría en curso y sin bloqueo."""
    if a.get("status") != "IN_PROGRESS" or final_locked(a["id"]):
        return False
    jefe = "audit:report_approve_jefe" in perms() and can_review_domain(a.get("audit_domain", "GENERAL"))
    return repo.is_member(a["id"], me()) or jefe


def thresholds(a=None):
    """Escala de calificación: Sistemas usa la parametrizada (5 niveles); el resto de auditorías, la de 3 niveles."""
    if a is not None and not is_systems(a):
        return dict(scoring.AUDIT_THRESHOLDS)
    return repo.thresholds() or scoring.DEFAULT_THRESHOLDS


def _phase_snapshot(a, trigger_action, report=None, reason=None):
    """Prepara una instantánea para insertarla en la transacción del evento."""
    return {
        "audit_id": str(a["id"]),
        "phase": a["phase"],
        "trigger_action": trigger_action,
        "captured_by": str(me()),
        "captured_username": (getattr(g, "claims", {}) or {}).get("username"),
        "report_id": str(report["id"]) if report else None,
        "report_version": report.get("version") if report else None,
        "scorecard": score_snapshots.build_scorecard(
            a, repo.worksheets_with_items(a["id"]), thresholds(a),
            evidence=repo.evidence(a["id"]), reason=reason,
        ),
    }


def _change(a, entity_type, entity_id, action, changes=None, reason=None, report=None):
    """Agrega a la transacción en curso un evento de la bitácora del expediente.

    Debe llamarse inmediatamente antes de la operación del repositorio que confirma
    el cambio: el evento y el cambio se confirman juntos o no se confirma ninguno.
    """
    claims = getattr(g, "claims", {}) or {}
    latest = repo.latest_final(a["id"])
    repo.stage_change({
        "audit_id": a["id"], "report_id": report["id"] if report else None,
        "entity_type": entity_type, "entity_id": entity_id, "action": action,
        "changes": changes or {}, "reason": reason, "audit_phase": a.get("phase"),
        "report_status": (report or latest or {}).get("status"),
        "actor_id": me(), "actor_username": claims.get("username"), "actor_roles": claims.get("roles", []),
        "request_id": getattr(g, "request_id", None),
    })


# ------------------------------------------------------------------ catálogos y expedientes
@bp.get("/codification")
@permission_required("audit:read", "audit:manage")
def codification_catalogs():
    """Catálogos de la codificación institucional para los formularios."""
    return jsonify({**codification.catalogs(),
                    "audit_kinds": {k: {"label": v["label"], "units": v["units"], "kinds": v["kinds"]} for k, v in AUDIT_KINDS.items()}})


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

    # Un expediente por unidad y período: las auditorías adicionales se abren dentro de él.
    existing = repo.open_file_for(unit_id, pf, pt)
    if existing:
        return err(
            f"Ya existe el expediente {existing['code']} abierto para esta unidad y período "
            f"({existing['audits']} auditoría(s)); cree la auditoría dentro de él.",
            409,
        )

    try:
        codes = codification.file_fields(d, domain, unit.get("kind"))
    except codification.CodeError as ex:
        return err(str(ex))
    try:
        fid, code = repo.create_file(
            unit_id,
            title,
            objective,
            pf,
            pt,
            me(),
            domain,
            audit_type=codes["audit_type"],
            company=codes["company"],
        )
    except IntegrityError:
        repo.db.session.rollback()
        return err("Ya existe un expediente abierto para esta unidad y período", 409)

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
            unit_kind = str(f.get("unit_kind") or "").upper()
            audit_kind = str(d.get("audit_kind") or ("OPERATIVA" if unit_kind == "SUCURSAL" else "ADMINISTRATIVA")).upper()
            rules = AUDIT_KINDS.get(audit_kind)
            if rules is None:
                return err("Tipo de auditoría: OPERATIVA, ESPECIAL, ADMINISTRATIVA o FINANCIERA")
            if unit_kind not in rules["units"]:
                return err(f"Una auditoría {rules['label'].split(' (')[0].lower()} no se aplica a una "
                           f"{'sucursal' if unit_kind == 'SUCURSAL' else 'unidad administrativa'}")
            lines = [l for l in d.get("lines", []) if l in ("AUTO", "PATRIMONIAL", "PERSONAL")]
            if set(rules["kinds"]) & {"SUSCRIPCION", "RECLAMO"} and audit_kind == "OPERATIVA" and not lines:
                return err("Seleccione al menos una línea (Auto, Patrimonial o Personal)")
            if not set(rules["kinds"]) & {"SUSCRIPCION", "RECLAMO"}:
                lines = []
            if set(rules["kinds"]) & set(GENERAL_KINDS):
                lines.append("GENERAL")
            if not lines:
                return err("Seleccione al menos una línea (Auto, Patrimonial o Personal)")
            d["audit_kind"] = audit_kind
            contact_name = txt(d, "contact_name", 0, 120) or ""
            contact_role = txt(d, "contact_role", 0, 120) or ""
        if len(contact_name) > 120 or len(contact_role) > 120:
            return err("Responsable de la unidad y cargo: máximo 120 caracteres")
        data = {"modality": modality, "audit_domain": domain, "lines": sorted(set(lines)),
                "audit_kind": "SISTEMAS" if domain == "SISTEMAS" else d["audit_kind"], "objectives": txt(d, "objectives", 10, 3000), "scope": txt(d, "scope", 10, 3000),
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
    # No existe el rol de líder: quien crea la auditoría queda como responsable interno del equipo.
    leader, members = str(d.get("leader_id") or me()), [str(m) for m in d.get("member_ids", [])]
    ids = list(dict.fromkeys([leader, *members]))
    if leader not in eligible or any(i not in eligible for i in ids):
        return err("El líder y los miembros deben ser auditores activos")
    if me() not in ids:
        return err("Usted debe formar parte del equipo que crea la auditoría")
    team = [{"user_id": i, "role": "LIDER" if i == leader else "AUDITOR", "initials": initials_of(eligible[i]["name"])} for i in ids]
    try:
        data.update(codification.report_fields(d, domain, data.get("audit_kind")))
    except codification.CodeError as ex:
        return err(str(ex))
    aid, code = repo.create_audit(f["id"], data, team, me())
    if domain == "SISTEMAS":
        try:
            repo.system_worksheet(aid, me())
        except Exception:  # noqa: BLE001
            repo.db.session.rollback()
            return err("La auditoría fue creada, pero no fue posible preparar el cuestionario ERP/TI", 500)
    log("AUDIT_CREATED", entity_type="audit", entity_id=aid, after_data={"code": code, "modality": modality, "lines": data["lines"]}, request_id=g.request_id)
    return jsonify(id=aid, code=code), 201


def overall_for(a, pairs, th):
    """Calificación global: promedio de cédulas (o ajuste manual); en Sistemas, además, por fases."""
    base = scoring.audit_summary([s for _, s in pairs], a.get("manual_score"), th)
    if not is_systems(a):
        return base
    return scoring.systems_overall(base, repo.audit_phase_scores(a["id"]), a.get("phase"), a.get("manual_score"), th)


def audit_overview(a):
    sheets = repo.worksheets_with_items(a["id"])
    th = thresholds(a)
    pairs = asm.summarize_sheets(sheets, th)
    overall = overall_for(a, pairs, th)
    reps = repo.reports(a["id"])
    obs = repo.observations(a["id"])
    return {"audit": a, "team": repo.team(a["id"]), "phase_log": repo.phase_log(a["id"]),
            "phase_snapshots": repo.phase_snapshots(a["id"]), "overall": overall, "thresholds": th,
            "indicators": scoring.evaluation_indicators(sheets, overall, th),
            "sheets": [{"id": ws["id"], "kind": ws["kind"], "line": ws["line"], "title": ws["title"], "criteria_count": len(ws["criteria"]),
                        "items": s.items, "scored": s.scored, "exceptions": s.exceptions, "auto": s.auto, "final": s.final,
                        "manual_override": s.manual_override, "rating": s.rating,
                        "statistics": sheet_statistics(ws)} for ws, s in pairs],
            "observations": len(obs), "evidence": len(repo.evidence(a["id"])), "reports": reps,
            "locked": final_locked(a["id"]),
            "can_edit_data": "audit:manage" in perms() and can_edit_data(a),
            "audit_kinds": {k: {"label": v["label"], "kinds": v["kinds"]} for k, v in AUDIT_KINDS.items()},
            "is_member": repo.is_member(a["id"], me())}


@bp.get("/<uuid:aid>")
@permission_required("audit:read")
def audit_detail(aid):
    a, e = load(aid)
    return e or jsonify(audit_overview(a))


@bp.put("/<uuid:aid>")
@permission_required("audit:manage")
def edit_audit(aid):
    """Edición de los datos generales por el equipo auditor o el Jefe de Auditoría del dominio, con motivo y bitácora."""
    a, e = load(aid)
    if e:
        return e
    if not can_edit_data(a):
        return err("Solo el equipo auditor o el Jefe de Auditoría pueden modificar los datos de esta auditoría", 403)
    d = request.get_json(silent=True) or {}
    try:
        upd = {}
        if "modality" in d:
            upd["modality"] = str(d["modality"] or "").upper()
            if upd["modality"] not in ("REMOTA", "PRESENCIAL"):
                raise ValueError("Modalidad: REMOTA o PRESENCIAL")
        for k, lo, hi in (("objectives", 10, 3000), ("scope", 10, 3000), ("procedures", 0, 3000), ("location", 0, 200),
                          ("contact_name", 0, 120), ("contact_role", 0, 120)):
            if k in d:
                upd[k] = txt(d, k, lo, hi)
        coding = {k: d[k] for k in ("plan_type", "process", "frequency", "report_company") if k in d}
        if coding:
            try:
                upd.update({k: v for k, v in codification.report_fields({**a, **coding}, a.get("audit_domain")).items() if k in coding})
            except codification.CodeError as ex:
                raise ValueError(str(ex))
        if "planned_start" in d:
            upd["planned_start"] = parse_date(d["planned_start"], "Inicio previsto")
        if "planned_end" in d:
            upd["planned_end"] = parse_date(d["planned_end"], "Fin previsto")
    except ValueError as ex:
        return err(str(ex))
    merged = {**a, **upd}
    if merged.get("modality") == "PRESENCIAL" and not merged.get("location"):
        return err("En una auditoría presencial indique el lugar")
    if merged.get("planned_start") and merged.get("planned_end") and merged["planned_end"] < merged["planned_start"]:
        return err("La fecha de fin no puede ser anterior a la de inicio")
    changes = {k: {"before": a.get(k), "after": v} for k, v in upd.items() if a.get(k) != v}
    if not changes:
        return jsonify(status="OK", note="Sin cambios")
    reason = str(d.get("reason") or "").strip()[:1000]
    if len(reason) < 10:
        return err("Indique el motivo de la modificación (mínimo 10 caracteres)")
    _change(a, "audit", a["id"], "AUDIT_DATA_UPDATED", changes, reason=reason)
    repo.update_audit_data(a["id"], {k: upd[k] for k in changes})
    log("AUDIT_DATA_UPDATED", entity_type="audit", entity_id=a["id"], before_data={k: v["before"] for k, v in changes.items()},
        after_data={k: v["after"] for k, v in changes.items()}, metadata={"reason": reason}, request_id=g.request_id)
    return jsonify(status="OK")


@bp.post("/<uuid:aid>/phase")
@permission_required("audit:manage")
def phase(aid):
    a, e = load(aid, write=True)
    if e:
        return e
    d = request.get_json(silent=True) or {}
    to, note = str(d.get("to", "")).upper(), str(d.get("note") or "").strip()[:500]
    seq = phases_for(a)
    if a["phase"] not in seq:
        return err(f"La fase actual ({a['phase']}) no corresponde al tipo de auditoría", 409)
    cur = seq.index(a["phase"])
    if to not in seq or abs(seq.index(to) - cur) != 1:
        return err("Solo se avanza o retrocede una fase a la vez")
    forward = seq.index(to) > cur
    sheets = repo.worksheets_with_items(a["id"])
    if to == "TRABAJO_CAMPO" and a["phase"] == "PLANIFICACION" and not sheets:
        return err("Para pasar a Trabajo de campo cree al menos una cédula en Planificación")
    scored_check = (forward and is_systems(a)) or to == "INFORME"
    if scored_check:
        empty = [ws["title"] for ws in sheets if not any(scoring.item_score(ws["criteria"], i["results"]) is not None for i in ws["items"])]
        if not sheets or empty:
            return err("Para cerrar la fase, cada cédula debe tener al menos un control calificado" + (": " + ", ".join(empty) if empty else ""))
    if not forward and not note:
        return err("Para retroceder de fase indique el motivo")
    snapshot = _phase_snapshot(a, "PHASE_CHANGE", reason=note)
    phase_score = None
    if forward and is_systems(a) and a["phase"] in scoring.SYSTEM_SCORED_PHASES:
        # Nota oficial de la fase que se cierra: la calificación vigente con la fórmula actual.
        card = snapshot["scorecard"]["overall"]
        phase_score = {"score": card.get("final"), "rating": card.get("rating") or "SIN_CALIFICAR",
                       "detail": {"auto": card.get("auto"), "items": card.get("items"), "scored": card.get("scored"),
                                  "worksheets": [{"id": w["id"], "title": w["title"], "final": w["final"], "rating": w["rating"]}
                                                 for w in snapshot["scorecard"]["worksheets"]]}}
    _change(a, "audit", a["id"], "PHASE_CHANGED",
            {"phase": {"before": a["phase"], "after": to},
             **({"phase_score": {"phase": a["phase"], "score": phase_score["score"]}} if phase_score else {})},
            reason=note or None)
    repo.change_phase(a["id"], a["phase"], to, me(), note, phase_snapshot=snapshot, phase_score=phase_score)
    log("AUDIT_PHASE_CHANGED", entity_type="audit", entity_id=a["id"], before_data={"phase": a["phase"]}, after_data={"phase": to, "note": note}, request_id=g.request_id)
    return jsonify(phase=to)


@bp.put("/<uuid:aid>/rating")
@permission_required("audit:rate")
def audit_rating(aid):
    a, e = load(aid, write=True, phases="WORK")
    if e:
        return e
    d = request.get_json(silent=True) or {}
    if d.get("clear"):
        before = {
            "manual": float(a["manual_score"]) if a.get("manual_score") is not None else None,
            "reason": a.get("manual_reason"),
        }
        _change(a, "audit", a["id"], "AUDIT_RATING_CLEARED", {"manual_score": {"before": before["manual"], "after": None}},
                reason="Se retira el ajuste manual de la calificación global")
        repo.set_audit_manual(a["id"], None, None, me())
        log(
            "AUDIT_RATING_CLEARED",
            entity_type="audit",
            entity_id=a["id"],
            before_data=before,
            after_data={"manual": None, "reason": None},
            request_id=g.request_id,
        )
        return jsonify(status="OK")
    try:
        score, reason = scoring.validate_manual(d.get("score"), d.get("reason"))
    except scoring.ScoreError as ex:
        return err(str(ex))
    _change(a, "audit", a["id"], "AUDIT_RATING_OVERRIDDEN",
            {"manual_score": {"before": float(a["manual_score"]) if a.get("manual_score") is not None else None, "after": score}},
            reason=reason)
    repo.set_audit_manual(a["id"], score, reason, me())
    log(
        "AUDIT_RATING_OVERRIDDEN",
        entity_type="audit",
        entity_id=a["id"],
        before_data={
            "manual": float(a["manual_score"]) if a.get("manual_score") is not None else None,
            "reason": a.get("manual_reason"),
        },
        after_data={"manual": score, "reason": reason},
        request_id=g.request_id,
    )
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
        phases="PLAN",
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

    if not is_systems(a):
        allowed = AUDIT_KINDS.get(a.get("audit_kind") or "", {}).get("kinds", ())
        if kind not in allowed:
            return err("Esa cédula no corresponde a este tipo de auditoría")
        if (kind in GENERAL_KINDS) != (line == "GENERAL"):
            return err("Línea inválida para esa cédula")

    # Las cédulas de línea General (cuestionarios, cuentas por pagar...) no dependen de las líneas de negocio elegidas.
    if line not in a["lines"] and not (line == "GENERAL" and kind in GENERAL_KINDS and not is_systems(a)):
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

            _change(a, "worksheet", None, "WORKSHEET_CREATED", {"kind": kind, "line": line})
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

        _change(a, "worksheet", None, "WORKSHEET_CREATED", {"kind": kind, "line": line, "template_version": ver})
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


def _phase_rules(a):
    """Reglas de edición de controles de Sistemas según la fase (verificación progresiva)."""
    phase = a.get("phase")
    return {
        "phase": phase,
        "lock_control": is_systems(a) and phase == "DOCUMENTACION",
        "only_documented": is_systems(a) and phase == "PRUEBAS_CAMPO",
    }


def _closed_answer(it, phase, code, field):
    """Respuesta de un control al cierre de una fase anterior (o None si la fase no se cerró)."""
    closed = ((it.get("phase_results") or {}).get(phase) or {}).get("results") or {}
    value = closed.get(code)
    return str(value.get(field) or "").upper() if isinstance(value, dict) else None


def _item_phase_guard(a, it, results=None):
    """Error (respuesta) si la fase no permite este cambio en el control, o None."""
    rules = _phase_rules(a)
    code = it.get("ref")
    if rules["only_documented"] and _closed_answer(it, "DOCUMENTACION", code, "documental") not in (None, "SI"):
        return err("En Pruebas de campo solo se prueban los controles documentados (SI) en la fase de Documentación", 409)
    if rules["lock_control"] and results:
        before = _closed_answer(it, "LEVANTAMIENTO", code, "control")
        for k, v in results.items():
            if before in ("SI", "NO") and isinstance(v, dict) and str(v.get("control") or "").upper() not in ("", before):
                return err("En Documentación la existencia del control se mantiene como en el Levantamiento; "
                           "aquí se verifican el soporte documental y la evidencia", 409)
    return None


def sheet_statistics(ws):
    """Estadísticas propias de la cédula: cuestionario de Sistemas o cuestionario por bloques (LOPCYMAT, servicios...)."""
    if ws["kind"] == "SISTEMAS":
        return scoring.system_statistics(ws["criteria"], ws["items"])
    if scoring.is_questionnaire(ws["criteria"]):
        return {**scoring.questionnaire_summary(ws["criteria"], ws["items"]), "index_label": scoring.index_label(ws["kind"])}
    return None


def ws_for(ws_id, write=False):
    ws = repo.get_worksheet(ws_id)
    if ws is None:
        return None, None, err("No encontrada", 404)
    a, e = load(ws["audit_id"], write=write, phases="ITEMS" if write else None)
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
    s = scoring.worksheet_summary(ws["criteria"], ws["items"], ws["manual_score"], thresholds(a))
    stats = sheet_statistics(ws)
    return jsonify(worksheet=ws, summary=s.__dict__, statistics=stats, audit={"id": a["id"], "code": a["code"], "phase": a["phase"], "status": a["status"]},
                   editable=repo.is_member(a["id"], me()) and a["status"] == "IN_PROGRESS" and a["phase"] in phase_group(a, "ITEMS")
                   and not final_locked(a["id"]),
                   phase_rules=_phase_rules(a))

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

    _change(a, "worksheet", ws["id"], "SYSTEM_QUESTIONNAIRE_IMPORTED",
            {"filename": name, "controls": len(rows), "previous_items": len(ws.get("items") or [])})
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

    # Fase 1: las brechas de la cédula se convierten en observaciones redactadas por el motor de reglas.
    created_obs = _auto_observations(a, fresh) if a.get("phase") == "LEVANTAMIENTO" else 0

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
        observations_created=created_obs,
        questionnaire_type=parsed["questionnaire_type"],
        questionnaire_name=parsed.get("questionnaire_name"),
        source_filename=name,
        sheets=parsed.get("sheets") or [],
        controls=imported_count,
        evidence_id=eid,
        sha256=sha,
        statistics=stats,
    )



def systems_domains():
    """Catálogo vigente del motor de Sistemas; si la tabla aún no existe o está vacía, el incorporado."""
    try:
        return observation_rules.domains_from_rows(repo.systems_rule_catalog())
    except Exception:  # noqa: BLE001
        repo.db.session.rollback()
        current_app.logger.exception("No se pudo leer el catálogo del motor de Sistemas; se usa el incorporado")
        return None


def _auto_observations(a, ws):
    """Redacta las observaciones de las brechas de la cédula, agrupadas por dominio de control, en una transacción.

    Las observaciones automáticas individuales que nadie editó se reemplazan por las consolidadas;
    los controles cubiertos por observaciones manuales o ya editadas no se vuelven a redactar.
    """
    criteria = {c["code"]: c for c in ws["criteria"]}
    replaceable = repo.consolidable_auto_observations(a["id"])
    replace_ids = {o["id"] for o in replaceable}
    covered = repo.observed_item_ids(a["id"], exclude=replace_ids)
    rows = []
    for it in ws["items"]:
        crit = criteria.get(it["ref"])
        # Las observaciones salen del Levantamiento: si esa fase ya se cerró, se usan sus respuestas.
        closed = ((it.get("phase_results") or {}).get("LEVANTAMIENTO") or {}).get("results") or {}
        result = closed.get(it["ref"]) if it["ref"] in closed else (it.get("results") or {}).get(it["ref"])
        if crit is None or not isinstance(result, dict) or it["id"] in covered:
            continue
        rows.append((crit, result, it.get("observation"), it["id"]))
    drafts = observation_rules.consolidate(rows, systems_domains())
    # Un control que queda solo en su dominio y ya tiene su observación automática no se rehace:
    # solo se reemplazan las individuales que efectivamente se agrupan con otras.
    replaceable_items = {i for o in replaceable for i in (o["covered"] or [])}
    drafts = [d for d in drafts if not (len(d["covered_items"]) == 1 and d["covered_items"][0] in replaceable_items)]
    if not drafts:
        return 0
    item_ids = {i for d in drafts for i in d["covered_items"]}
    superseded = [o["id"] for o in replaceable if set(o["covered"] or []) & item_ids]
    try:
        first_id = None
        for o in drafts:
            fields = {k: o[k] for k in ("title", "condition", "criteria", "cause", "effect", "recommendation", "risk")}
            fields.update(item_id=o["item_id"], covered_items=o["covered_items"])
            _change(a, "observation", None, "OBSERVATION_AUTO_CREATED",
                    {"controls": o["controls"], "gap": o["gap"], "domain": o["domain"], "risk": o["risk"]},
                    reason="Redactada por el motor de reglas a partir de la cédula (consolidada por dominio)")
            oid, _ = repo.add_observation(a["id"], fields, me(), origin="AUTO", commit=False)
            first_id = first_id or oid
            replaced = [r for r in replaceable if set(r["covered"] or []) & set(o["covered_items"])]
            if replaced:
                repo.supersede_observations([r["id"] for r in replaced], oid)
                _change(a, "observation", oid, "OBSERVATIONS_CONSOLIDATED",
                        {"replaced": [r["id"] for r in replaced], "controls": o["controls"]},
                        reason="Observaciones automáticas individuales agrupadas por dominio de control")
        repo.db.session.commit()
    except Exception:
        repo.db.session.rollback()
        raise
    log("OBSERVATIONS_AUTO_CREATED", entity_type="worksheet", entity_id=ws["id"],
        after_data={"creadas": len(drafts), "reemplazadas": len(superseded)}, request_id=g.request_id)
    return len(drafts)


@bp.post("/worksheets/<uuid:wid>/auto-observations")
@permission_required("audit:manage")
def auto_observations(wid):
    """Genera o consolida las observaciones de las brechas del Levantamiento de una cédula de Sistemas.

    En la fase 1 redacta las de las brechas nuevas; en las fases 2 y 3 consolida por dominio las
    observaciones automáticas que nadie editó, con las respuestas con que se cerró el Levantamiento.
    """
    ws, a, e = ws_for(wid)
    if e:
        return e
    a, e = load(a["id"], write=True, phases=scoring.SYSTEM_SCORED_PHASES)
    if e:
        return e
    if ws["kind"] != "SISTEMAS" or not is_systems(a):
        return err("Disponible solo para cédulas de Auditoría de Sistemas", 400)
    n = _auto_observations(a, ws)
    return jsonify(created=n, note=f"Se crearon {n} observación(es) agrupadas por dominio. Revíselas y ajústelas antes del informe." if n
                   else "No hay brechas nuevas ni observaciones automáticas por consolidar.")


@bp.post("/<uuid:aid>/auto-observations")
@permission_required("audit:manage")
def audit_auto_observations(aid):
    """Hallazgos automáticos de las auditorías no de Sistemas, con criterios normativos SUDEASEG.

    Recorre las cédulas de la auditoría, agrupa los criterios incumplidos de la muestra por tema
    normativo y crea un hallazgo por cédula y tema que todavía no tenga su observación automática.
    """
    a, e = load(aid, write=True, phases="WORK")
    if e:
        return e
    if is_systems(a):
        return err("En Auditoría de Sistemas use la generación desde la cédula", 400)
    catalog = repo.regulatory_catalog()
    if not catalog:
        return err("El catálogo normativo no está configurado", 409)
    existing = repo.active_rule_keys(a["id"])
    drafts = [o for ws in repo.worksheets_with_items(a["id"]) for o in regulatory_rules.findings(ws, catalog)
              if o["rule_key"] not in existing]
    if not drafts:
        return jsonify(created=0, note="No hay incumplimientos nuevos sin hallazgo.")
    try:
        for o in drafts:
            fields = {k: o[k] for k in ("title", "condition", "criteria", "cause", "effect", "recommendation", "risk", "rule_key")}
            fields.update(item_id=o["item_id"], covered_items=o["covered_items"])
            _change(a, "observation", None, "OBSERVATION_AUTO_CREATED",
                    {"criteria": o["controls"], "topic": o["topic"], "risk": o["risk"]},
                    reason="Redactada por el motor de reglas (normativa SUDEASEG) a partir de los incumplimientos de la cédula")
            repo.add_observation(a["id"], fields, me(), origin="AUTO", commit=False)
        repo.db.session.commit()
    except Exception:
        repo.db.session.rollback()
        raise
    log("OBSERVATIONS_AUTO_CREATED", entity_type="audit", entity_id=a["id"], after_data={"creadas": len(drafts)}, request_id=g.request_id)
    return jsonify(created=len(drafts), note=f"Se crearon {len(drafts)} hallazgo(s). Revíselos y ajústelos antes del informe.")


@bp.get("/regulatory-catalog")
@permission_required("audit:read", "audit:template_manage")
def regulatory_catalog():
    return jsonify(topics=repo.regulatory_catalog())


@bp.put("/regulatory-catalog/<topic>")
@permission_required("audit:template_manage", step_up=True)
def update_regulatory_catalog(topic):
    """Contraloría ajusta los textos normativos (y puede agregar artículos) de un tema del catálogo."""
    d = request.get_json(silent=True) or {}
    try:
        upd = {k: txt(d, k, 10, 3000) for k in ("criteria", "cause", "effect", "recommendation") if k in d}
        if "label" in d:
            upd["label"] = txt(d, "label", 3, 120)
        if "keywords" in d:
            kws = [str(k).strip().lower()[:60] for k in (d.get("keywords") or []) if str(k).strip()]
            if len(kws) > 60:
                raise ValueError("Máximo 60 palabras clave")
            upd["keywords"] = kws
    except ValueError as ex:
        return err(str(ex))
    if not upd:
        return err("Nada que actualizar")
    before = next((t for t in repo.regulatory_catalog() if t["topic"] == topic), None)
    if before is None or not repo.update_regulatory_topic(topic, upd, me()):
        return err("Tema no encontrado", 404)
    log("REGULATORY_CATALOG_UPDATED", entity_type="regulatory_topic", entity_id=topic,
        before_data={k: before.get(k) for k in upd}, after_data=upd, request_id=g.request_id)
    return jsonify(status="OK")


def file_slug(text_, limit=60):
    """Texto apto para nombres de archivo (sin acentos ni signos): «Gerencia de TI» -> «Gerencia_de_TI»."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(text_ or "")).encode("ascii", "ignore").decode()
    return (re.sub(r"[^A-Za-z0-9]+", "_", plain).strip("_")[:limit].rstrip("_")) or "unidad"


def _systems_document(aid, kind):
    """Carta de documentación (fase 2) o programa de pruebas (fase 3) de una auditoría de Sistemas."""
    a, e = load(aid)
    if e:
        return e
    if not is_systems(a):
        return err("Disponible solo para Auditoría de Sistemas", 400)
    needed = "DOCUMENTACION" if kind == "documentation" else "PRUEBAS_CAMPO"
    if SYSTEM_PHASES.index(a["phase"]) < SYSTEM_PHASES.index(needed):
        return err(f"Disponible desde la fase {needed.replace('_', ' ').title()}", 409)
    sheets = repo.worksheets_with_items(a["id"])
    team = _team_info(a["id"])
    company = repo.company() or current_app.config["COMPANY_NAME"]
    if kind == "documentation":
        try:
            due = parse_date(request.args.get("due"), "Fecha límite")
        except ValueError as ex:
            return err(str(ex))
        controls = phase_documents.documented_controls(sheets, "LEVANTAMIENTO", systems_domains())
        pdf = phase_documents.documentation_request_pdf(audit=a, team=team, controls=controls, company=company, due=due, today=date.today())
        action, name = "DOCUMENTATION_REQUEST_ISSUED", f"{a['code']}_{file_slug(a.get('unit_name'))}_solicitud_documentacion.pdf"
        changes = {"controls": [c["ref"] for c in controls], "due": due}
    else:
        controls = phase_documents.documented_controls(sheets, "DOCUMENTACION", systems_domains())
        pdf = phase_documents.field_tests_pdf(audit=a, team=team, controls=controls, company=company, today=date.today())
        action, name = "FIELD_TEST_PROGRAM_ISSUED", f"{a['code']}_{file_slug(a.get('unit_name'))}_programa_pruebas_campo.pdf"
        changes = {"controls": [c["ref"] for c in controls]}
    if repo.is_member(a["id"], me()):
        _change(a, "audit", a["id"], action, {**changes, "sha256": hashlib.sha256(pdf).hexdigest()})
        repo.db.session.commit()
    log(action, entity_type="audit", entity_id=a["id"], after_data={"controles": len(controls)}, request_id=g.request_id)
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.get("/<uuid:aid>/documentation-request.pdf")
@permission_required("audit:read")
def documentation_request(aid):
    return _systems_document(aid, "documentation")


@bp.get("/<uuid:aid>/field-tests.pdf")
@permission_required("audit:read")
def field_tests(aid):
    return _systems_document(aid, "tests")


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
        _change(a, "worksheet", str(wid), "SYSTEM_CONTROL_ADDED", {"text": text, "section": section, "weight": weight})
        code = repo.add_system_control(wid, text, section, weight, me())
    except ValueError as ex:
        repo.db.session.rollback()
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
    _change(a, "worksheet", ws["id"], "ITEMS_ADDED", {"refs": list(dict.fromkeys(refs))})
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
    _change(a, "worksheet", ws["id"], "SAMPLE_DRAWN", {"requested": n, "refs": list(refs)})
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
            if control == "PARCIAL":
                return err("En Auditoría de Sistemas el control se responde solo SI o NO")
            if control in scoring.SYSTEM_CONTROL_VALUES or doc in scoring.SYSTEM_DOC_POINTS or evidence in scoring.SYSTEM_EVIDENCE_POINTS:
                results[k] = {"control": control if control in scoring.SYSTEM_CONTROL_VALUES else "", "documental": doc if doc in scoring.SYSTEM_DOC_POINTS else "", "evidencia": evidence if evidence in scoring.SYSTEM_EVIDENCE_POINTS else ""}
    else:
        valid = set(scoring.POINTS) | {"NO_APLICA", "EXCEPCION"}
        results = {k: v for k, v in raw_results.items() if k in codes and v in valid}
    guard = _item_phase_guard(a, it, results)
    if guard:
        return guard
    obs = str(d.get("observation") or "").strip()[:2000] or None
    exc = str(d.get("info_exception") or "").strip()[:2000] or None
    if "EXCEPCION" in results.values() and not exc:
        return err("Marcó EXCEPCION: describa la información no recibida en el campo de excepción")
    if scoring.is_questionnaire(ws["criteria"]) and set(results.values()) & set(scoring.NEGATIVE_ANSWERS) and not obs:
        return err("Respuesta negativa: incluya una breve reseña del motivo en la observación")
    before = {"results": it.get("results") or {}, "observation": it.get("observation"), "info_exception": it.get("info_exception")}
    after = {"results": results, "observation": obs, "info_exception": exc}
    _change(a, "item", str(iid), "ITEM_UPDATED",
            {k: {"before": before[k], "after": after[k]} for k in before if before[k] != after[k]},
            reason=str(d.get("reason") or "").strip()[:500] or None)
    repo.update_item(iid, results, obs, exc, scoring.item_score(ws["criteria"], results), me())
    log(
        "ITEM_UPDATED",
        entity_type="item",
        entity_id=str(iid),
        before_data={
            "results": it.get("results") or {},
            "observation": it.get("observation"),
            "info_exception": it.get("info_exception"),
            "auto_score": float(it["auto_score"]) if it.get("auto_score") is not None else None,
        },
        after_data={
            "results": results,
            "observation": obs,
            "info_exception": exc,
            "auto_score": scoring.item_score(ws["criteria"], results),
        },
        metadata={"ref": it["ref"], "source": "ONLINE"},
        request_id=g.request_id,
    )
    return jsonify(auto_score=scoring.item_score(ws["criteria"], results))


def _rate(kind_label, entity_id, current, current_reason, setter, a):
    d = request.get_json(silent=True) or {}
    before = {
        "manual": float(current) if current is not None else None,
        "reason": current_reason,
    }
    if d.get("clear"):
        _change(a, kind_label.lower(), entity_id, kind_label + "_RATING_CLEARED",
                {"manual_score": {"before": before["manual"], "after": None}},
                reason="Se retira el ajuste manual y se vuelve a la calificación automática")
        setter(None, None)
        log(
            kind_label + "_RATING_CLEARED",
            entity_type=kind_label.lower(),
            entity_id=entity_id,
            before_data=before,
            after_data={"manual": None, "reason": None},
            request_id=g.request_id,
        )
        return jsonify(status="OK")
    try:
        score, reason = scoring.validate_manual(d.get("score"), d.get("reason"))
    except scoring.ScoreError as ex:
        return err(str(ex))
    _change(a, kind_label.lower(), entity_id, kind_label + "_RATING_OVERRIDDEN",
            {"manual_score": {"before": before["manual"], "after": score}}, reason=reason)
    setter(score, reason)
    log(
        kind_label + "_RATING_OVERRIDDEN",
        entity_type=kind_label.lower(),
        entity_id=entity_id,
        before_data=before,
        after_data={"manual": score, "reason": reason},
        request_id=g.request_id,
    )
    return jsonify(status="OK")


@bp.put("/items/<uuid:iid>/rating")
@permission_required("audit:rate")
def item_rating(iid):
    it = repo.get_item(iid)
    if it is None:
        return err("No encontrado", 404)
    ws, a, e = ws_for(it["worksheet_id"], write=True)
    if not e:
        e = _item_phase_guard(a, it)
    return e or _rate("ITEM", str(iid), it["manual_score"], it.get("manual_reason"), lambda s, r: repo.set_item_manual(iid, s, r, me()), a)


@bp.put("/worksheets/<uuid:wid>/rating")
@permission_required("audit:rate")
def sheet_rating(wid):
    ws, a, e = ws_for(wid, write=True)
    return e or _rate("WORKSHEET", ws["id"], ws["manual_score"], ws.get("manual_reason"), lambda s, r: repo.set_ws_manual(wid, s, r, me()), a)


# ------------------------------------------------------------------ observaciones
OBS_FINDING_FIELDS = ("title", "condition", "criteria", "cause", "effect", "recommendation", "risk")


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
    a, e = load(aid, write=True, phases="WORK")
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
    _change(a, "observation", None, "OBSERVATION_CREATED", {k: {"before": None, "after": v} for k, v in fields.items()},
            reason="Registro original")
    oid, seq = repo.add_observation(a["id"], fields, me())
    log("OBSERVATION_CREATED", entity_type="observation", entity_id=oid, after_data={"seq": seq, **fields}, request_id=g.request_id)
    return jsonify(id=oid, seq=seq), 201


@bp.put("/observations/<uuid:oid>")
@permission_required("audit:manage")
def edit_observation(oid):
    o = repo.get_observation(oid)
    if o is None:
        return err("No encontrada", 404)
    a, e = load(o["audit_id"], write=True, phases="WORK")
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
    upd = {k: v for k, v in upd.items() if o.get(k) != v}
    if not upd:
        return jsonify(status="OK", note="Sin cambios")
    # Toda modificación queda como una nueva revisión con su motivo. La respuesta de la
    # unidad y el seguimiento del PAC llevan un motivo por defecto; el hallazgo, uno explícito.
    reason = str(d.get("reason") or "").strip()[:1000]
    if set(upd) & set(OBS_FINDING_FIELDS) and len(reason) < 10:
        return err("Indique el motivo de la modificación de la observación (mínimo 10 caracteres)")
    reason = reason if len(reason) >= 10 else "Registro de la respuesta de la unidad / seguimiento del PAC"
    latest = repo.latest_final(a["id"])
    _change(a, "observation", str(oid), "OBSERVATION_UPDATED",
            {k: {"before": o.get(k), "after": v} for k, v in upd.items()}, reason=reason)
    repo.update_observation(oid, upd, me(), reason, latest["status"] if latest else None)
    log(
        "OBSERVATION_UPDATED",
        entity_type="observation",
        entity_id=str(oid),
        before_data={key: o.get(key) for key in upd},
        after_data=upd,
        metadata={"campos": sorted(upd)},
        request_id=g.request_id,
    )
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
    item_id, obs_id = request.form.get("item_id") or None, request.form.get("observation_id") or None
    # La evidencia solo puede vincularse a ítems y observaciones de esta misma auditoría.
    try:
        if item_id:
            item_id = str(uuid.UUID(str(item_id)))
            item = repo.get_item(item_id)
            item_ws = repo.get_worksheet(item["worksheet_id"], with_items=False) if item else None
            if item_ws is None or str(item_ws.get("audit_id")) != str(a["id"]):
                return err("El ítem asociado debe pertenecer a la misma auditoría.", 400)
        if obs_id:
            obs_id = str(uuid.UUID(str(obs_id)))
            obs = repo.get_observation(obs_id)
            if obs is None or str(obs["audit_id"]) != str(a["id"]):
                return err("La observación asociada debe pertenecer a la misma auditoría.", 400)
    except (TypeError, ValueError):
        return err("Identificador de ítem u observación inválido", 400)
    sha = hashlib.sha256(data).hexdigest()
    eid_ = str(uuid.uuid4())
    key = f"evidence/{a['id']}/{eid_}"
    storage.put(key, data)
    _change(a, "evidence", eid_, "EVIDENCE_ADDED",
            {"filename": name, "sha256": sha, "item_id": item_id, "observation_id": obs_id})
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
    a, e = load(aid, write=True, phases="WORK")
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
    a, e = load(aid, write=True, phases="WORK")
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
    _change(a, "audit", a["id"], "OFFLINE_IMPORTED", {
        "file_sha256": sha, "summary": summary, "overwrite": overwrite,
        "rows": [{k: v for k, v in p.items() if k != "data"} for p in plan if p["status"] != "UNCHANGED"][:500],
    })
    done = repo.apply_offline(plan, {wid: ws["criteria"] for wid, ws in sheets.items()}, me())
    log("OFFLINE_IMPORTED", entity_type="audit", entity_id=a["id"], metadata={"archivo_sha256": sha, "aplicadas": done, **summary, "sobrescribir": overwrite}, request_id=g.request_id)
    return jsonify(dry_run=False, applied=done, summary=summary)


# ------------------------------------------------------------------ informes
def _team_info(aid):
    return [{"name": t["name"], "initials": t["initials"], "role": t["role"], "user_id": t["user_id"],
             "system_role": t.get("system_role")} for t in repo.team(aid)]


def _make_body(a, kind, version, conclusion, revision=1, report_code=None):
    """Cuerpo del informe con los datos vigentes y su trazabilidad.

    El historial (instantáneas por fase, revisiones de observaciones y decisiones de revisión
    anteriores) queda dentro del cuerpo y, por tanto, dentro del SHA-256 que aprueban los revisores.
    """
    team = _team_info(a["id"])
    history = None
    if kind == "FINAL":
        reports_ = [r for r in repo.reports(a["id"]) if r["kind"] == "FINAL"]
        history = {
            "snapshots": repo.phase_snapshots(a["id"]),
            "observation_revisions": repo.observation_revisions(a["id"]),
            "transitions": repo.audit_report_transitions(a["id"]),
            "review_points": [p for r in reports_ for p in repo.review_points(r["id"])],
            "reopenings": [{"version": r["version"], **o} for r in reports_ for o in [repo.reopening(r["id"])] if o],
        }
    return asm.assemble(
        kind=kind, audit=a, file={"code": a["file_code"], "title": a["title"], "period_from": a["period_from"], "period_to": a["period_to"]},
        unit={"code": a["unit_code"], "name": a["unit_name"], "kind": a["unit_kind"]}, team=team,
        worksheets=repo.worksheets_with_items(a["id"]), observations=repo.observations(a["id"]), evidence=repo.evidence(a["id"]),
        thresholds=thresholds(a), company=repo.company() or current_app.config["COMPANY_NAME"], version=version, today=date.today(), conclusion=conclusion,
        history=history, revision=revision, overall_for=lambda pairs, th: overall_for(a, pairs, th), report_code=report_code)


def _transition(rep, status, action, delegation=None, **kw):
    """Aplica la transición validada sobre el estado y contenido leídos; None si se aplicó, o la respuesta 409.

    Si quien actúa es un suplente, la transición registra la suplencia y el titular ("en nombre de").
    """
    claims = getattr(g, "claims", {}) or {}
    try:
        repo.transition_report(
            rep["id"], expected_status=rep["status"], expected_sha256=rep["body_sha256"],
            status=status, action=action, actor=me(), report_version=rep["version"],
            actor_username=claims.get("username"), actor_roles=claims.get("roles", []),
            delegation_id=delegation["id"] if delegation else None,
            on_behalf_of=delegation["titular_id"] if delegation else None, **kw,
        )
    except repo.StaleReportState as ex:
        log(
            "AUDIT_REPORT_TRANSITION_CONFLICT", outcome="DENIED", entity_type="audit_report",
            entity_id=str(rep["id"]), metadata={"action": action, "expected_status": rep["status"], "to": status},
            request_id=g.request_id,
        )
        return err(str(ex), 409)
    return None


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
    return build_pdf(rep["body"], {"final": final, "initials": {t["name"]: valid.get(t["user_id"]) for t in team}, "collaborator": collab,
                                   "jefe_signature": _jefe_signature(rep),
                                   "transitions": repo.report_transitions(rep["id"]), "body_sha256": rep["body_sha256"],
                                   "review_points": [p for r in repo.reports(rep["audit_id"]) if r["kind"] == "FINAL"
                                                     for p in repo.review_points(r["id"])]})


def _jefe_signature(rep):
    """Firma escaneada del Jefe de Auditoría que aprobó el contenido vigente (los auditores del equipo solo estampan iniciales)."""
    if rep.get("kind") != "FINAL" or not rep.get("jefe_approved_by") or rep.get("jefe_approved_body_sha256") != rep["body_sha256"]:
        return None
    approval = next((t for t in reversed(repo.report_transitions(rep["id"]))
                     if t["action"] == "APPROVE_JEFE" and t["body_sha256"] == rep["body_sha256"]), None)
    sig = repo.active_signature(rep["jefe_approved_by"])
    if sig is None:
        return None
    return {"name": sig["full_name"], "image": sig["content"],
            "on_behalf_of": approval.get("on_behalf_of") if approval else None,
            "date": str(approval["created_at"])[:10] if approval else None}


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
    # audit:read_final solo da acceso a informes aprobados o firmados; en la etapa
    # CONTRALOR el informe sigue en revisión y solo lo ven Gerencia y Contraloría.
    final_view = (
        (rep["status"] in ("APPROVED", "SIGNED") and "audit:read_final" in pset)
        or (
            rep["status"] in ("CONTRALOR", "APPROVED", "SIGNED")
            and (
                "audit:sign_gerente" in pset
                or "audit:sign_contralor" in pset
                or "audit:report_approve" in pset
            )
        )
    )
    if (
        a is not None
        and final_viewer
        and rep["kind"] == "FINAL"
        and (stage_view or final_view)
        and allowed_domain(a.get("audit_domain", "GENERAL"))
    ):
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
    a, e = load(aid, write=True, phases=("INFORME",) if kind == "FINAL" else "WORK")
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
    reason = "Generación inicial"
    if kind == "FINAL":
        previous = repo.latest_final(a["id"])
        reopened = repo.reopening(previous["id"]) if previous and previous["status"] == "SIGNED" else None
        if reopened:
            reason = f"Nueva versión autorizada por Contraloría tras la firma de la v{previous['version']}: {reopened['reason']}"
    code = repo.report_code_for(a["id"], kind, date.today().year)
    body = _make_body(a, kind, version, conclusion, report_code=code)
    _change(a, "audit_report", None, "AUDIT_REPORT_GENERATED",
            {"kind": kind, "version": version, "code": code, "sha256": body_hash(body)}, reason=reason)
    rid = repo.create_report(a["id"], kind, version, body, body_hash(body), me(), reason=reason, code=code)
    log("AUDIT_REPORT_GENERATED", entity_type="audit_report", entity_id=rid, after_data={"kind": kind, "version": version, "sha256": body_hash(body)}, request_id=g.request_id)
    return jsonify(id=rid, version=version), 201


@bp.get("/reports/<uuid:rid>")
@stage_required("audit:read", "audit:read_final")
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

    acting = acting_delegation(STATUS_STAGE.get(st.status), domain) if st.kind == "FINAL" else None
    return jsonify(
        acting_for=({"titular": acting["titular_name"], "stage": STAGE_LABEL[acting["stage"]], "ends_on": acting["ends_on"],
                     "needs_certificate": acting["stage"] in ("GERENCIA", "CONTRALOR") and repo.signing_certificate(me()) is None}
                    if acting else None),
        report=rep, team=team, comments=repo.comments(rid),
        transitions=repo.report_transitions(rid),
        body_revisions=repo.body_revisions(rid),
        review_points=repo.review_points(rid),
        reopening=repo.reopening(rid),
        signoffs=sos, signatures=visible_signatures,
        missing_initials=missing, is_member=member,
        can={
            "attend_points": member and st.status in ("DRAFT", "RETURNED") and "audit:manage" in pset,
            "reopen": (
                st.kind == "FINAL" and st.status == "SIGNED" and "audit:report_approve" in pset
                and not member and repo.reopening(rid) is None
                and (repo.latest_final(a["id"]) or {}).get("id") == rep["id"]
                and a.get("status") == "IN_PROGRESS"
            ),
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
    reason = str(d.get("reason") or "").strip()[:1000] or (
        "Corrección tras devolución" if rep["status"] == "RETURNED" else "Regeneración del borrador")
    revision = len(repo.body_revisions(rid)) + 1
    body = _make_body(a, rep["kind"], rep["version"], conclusion, revision=revision, report_code=rep.get("code"))
    _change(a, "audit_report", str(rid), "AUDIT_REPORT_REGENERATED",
            {"body_sha256": {"before": rep["body_sha256"], "after": body_hash(body)}, "revision": revision},
            reason=reason, report=rep)
    try:
        repo.replace_body(rid, body, body_hash(body), me(), reason, expected_sha256=rep["body_sha256"])
    except repo.StaleReportState as ex:
        return err(str(ex), 409)
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
    _change(a, "audit_report", str(rid), "REPORT_INITIALED", {"initials": mine["initials"], "body_sha256": rep["body_sha256"]}, report=rep)
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
    pending = [p for p in repo.review_points(rid) if p["status"] == "PENDIENTE"]
    if pending:
        return err(f"Quedan {len(pending)} punto(s) de la devolución sin atender; márquelos como atendidos antes de reenviar", 409)
    snapshot = (
        _phase_snapshot(a, "FINAL_REPORT_SUBMITTED", report=rep)
        if rep.get("kind") == "FINAL"
        else None
    )
    conflict = _transition(
        rep, "IN_REVIEW", "SUBMIT", submitted_at="now", phase_snapshot=snapshot
    )
    if conflict:
        return conflict
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
    conflict = _transition(rep, "SENT", "SEND_PREVIO", sent_to=f"{to_name}" + (f" <{email}>" if email else ""), sent_at="now", sent_by=me())
    if conflict:
        return conflict
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
@stage_required(
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

    d = request.get_json(silent=True) or {}
    t = str(d.get("comment") or "").strip()
    if len(t) < 10:
        return err("Indique qué debe corregirse (mínimo 10 caracteres)")
    try:
        points = _review_points(a, d.get("points") or [])
    except ValueError as ex:
        return err(str(ex))

    # Una devolución invalida las aprobaciones anteriores del contenido.
    # Los PDF firmados históricos se conservan, pero no se presentan como actuales;
    # las aprobaciones invalidadas siguen constando en report_transitions.
    conflict = _transition(
        rep, "RETURNED", "RETURN", delegation=acting_delegation(STATUS_STAGE[stage], a.get("audit_domain", "GENERAL")),
        comment=t, comment_kind="DEVOLUCION", review_points=points,
        approved_by=None, approved_at=None, approved_body_sha256=None,
        jefe_approved_by=None, jefe_approved_at=None, jefe_approved_body_sha256=None,
        gerente_approved_by=None, gerente_approved_at=None, gerente_approved_body_sha256=None,
        contralor_approved_by=None, contralor_approved_at=None, contralor_approved_body_sha256=None,
    )
    if conflict:
        return conflict
    log(
        "AUDIT_REPORT_RETURNED", entity_type="audit_report", entity_id=str(rid),
        metadata={"comment": t, "returned_from": stage}, request_id=g.request_id,
    )
    notify_report_returned(str(rid), a, stage, t, str(me()), getattr(g, "request_id", None))
    return jsonify(status="RETURNED")


POINT_TARGETS = ("GENERAL", "OBSERVATION", "ITEM", "WORKSHEET")


def _review_points(a, raw):
    """Valida los puntos a corregir de una devolución: cada destino debe pertenecer a la auditoría."""
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Los puntos de la devolución deben ser una lista de hasta 100 elementos")
    sheets = {ws["id"]: ws for ws in repo.worksheets_with_items(a["id"])}
    items = {it["id"]: (ws, it) for ws in sheets.values() for it in ws["items"]}
    observations = {o["id"]: o for o in repo.observations(a["id"])}
    out = []
    for p in raw:
        p = p if isinstance(p, dict) else {}
        target = str(p.get("target_type") or "GENERAL").upper()
        desc = str(p.get("description") or "").strip()
        if target not in POINT_TARGETS:
            raise ValueError("Tipo de punto inválido: GENERAL, OBSERVATION, ITEM o WORKSHEET")
        if not 5 <= len(desc) <= 2000:
            raise ValueError("Describa cada punto a corregir (5 a 2000 caracteres)")
        tid = str(p.get("target_id") or "").strip() or None
        label = None
        if target == "OBSERVATION":
            if tid not in observations:
                raise ValueError("La observación indicada no pertenece a esta auditoría")
            label = f"Observación {observations[tid]['seq']}: {observations[tid]['title']}"[:300]
        elif target == "ITEM":
            if tid not in items:
                raise ValueError("El ítem indicado no pertenece a esta auditoría")
            label = f"{items[tid][0]['title']} · {items[tid][1]['ref']}"[:300]
        elif target == "WORKSHEET":
            if tid not in sheets:
                raise ValueError("La cédula indicada no pertenece a esta auditoría")
            label = sheets[tid]["title"][:300]
        else:
            tid = None
        out.append({"target_type": target, "target_id": tid, "target_label": label, "description": desc})
    return out


@bp.post("/review-points/<int:pid>/attend")
@permission_required("audit:manage")
def attend_review_point(pid):
    """El equipo auditor marca un punto de la devolución como atendido, con nota obligatoria."""
    point = repo.get_review_point(pid)
    if point is None:
        return err("No encontrado", 404)
    rep, a, team, e = get_rep(point["report_id"], write=True)
    if e:
        return e
    if rep["status"] not in ("DRAFT", "RETURNED"):
        return err("Los puntos se atienden mientras el informe está devuelto o en borrador", 409)
    if point["status"] != "PENDIENTE":
        return err("El punto ya fue atendido", 409)
    note = str((request.get_json(silent=True) or {}).get("note") or "").strip()
    if not 10 <= len(note) <= 2000:
        return err("Explique cómo se atendió el punto (10 a 2000 caracteres)")
    _change(a, "review_point", str(pid), "REVIEW_POINT_ATTENDED",
            {"status": {"before": "PENDIENTE", "after": "ATENDIDO"}, "description": point["description"]},
            reason=note, report=rep)
    if not repo.attend_review_point(pid, me(), note):
        return err("El punto ya fue atendido", 409)
    repo.db.session.commit()
    log("REVIEW_POINT_ATTENDED", entity_type="review_point", entity_id=str(pid), after_data={"note": note}, request_id=g.request_id)
    return jsonify(status="ATENDIDO")


@bp.post("/reports/<uuid:rid>/reopen")
@permission_required("audit:report_approve", step_up=True)
def reopen_report(rid):
    """Contraloría autoriza una nueva versión de un informe final firmado.

    La versión firmada no se modifica: conserva su contenido, firmas y aprobaciones. La
    autorización solo desbloquea la auditoría para que el equipo genere la versión siguiente,
    que recorre de nuevo toda la cadena de revisión.
    """
    rep, a, team, e = get_rep(rid, final_viewer=True)
    if e:
        return e
    if rep["kind"] != "FINAL" or rep["status"] != "SIGNED":
        return err("Solo se reabre un informe final firmado", 409)
    if me() in [t["user_id"] for t in team]:
        return err("El equipo auditor no puede autorizar la reapertura de su propio informe", 403)
    latest = repo.latest_final(a["id"])
    if latest is None or latest["id"] != rep["id"]:
        return err("Solo se puede reabrir la última versión del informe final", 409)
    if a.get("status") != "IN_PROGRESS":
        return err("La auditoría está cerrada (PAC enviado): no se puede reabrir el informe", 409)
    if repo.reopening(rid):
        return err("Esta versión ya fue reabierta", 409)
    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if not 20 <= len(reason) <= 2000:
        return err("Indique el motivo de la reapertura (20 a 2000 caracteres)")
    _change(a, "audit_report", str(rid), "FINAL_REPORT_REOPENED",
            {"version": rep["version"], "body_sha256": rep["body_sha256"]}, reason=reason, report=rep)
    try:
        repo.reopen_report(rid, reason, me())
    except Exception:  # noqa: BLE001 - reapertura concurrente (UNIQUE)
        repo.db.session.rollback()
        return err("Esta versión ya fue reabierta", 409)
    log("AUDIT_REPORT_REOPENED", entity_type="audit_report", entity_id=str(rid), metadata={"reason": reason}, request_id=g.request_id)
    return jsonify(status="REOPENED", note="El equipo auditor puede generar la nueva versión del informe final.")


@bp.get("/<uuid:aid>/history")
@permission_required("audit:read", "audit:read_final")
def audit_history(aid):
    """Bitácora del expediente: cambios de datos y decisiones del flujo, en orden cronológico."""
    a, e = load(aid)
    if e:
        return e
    events = [{"source": "CHANGE", **ev} for ev in repo.change_events(a["id"])]
    events += [{"source": "TRANSITION", "entity_type": "audit_report", "entity_id": t["report_id"], **t}
               for t in repo.audit_report_transitions(a["id"])]
    events.sort(key=lambda ev: (ev["created_at"], ev["source"], ev["id"]))
    return jsonify(events=events, observation_revisions=repo.observation_revisions(a["id"]))


@bp.post("/reports/<uuid:rid>/approve/jefe")
@stage_required("audit:report_approve_jefe", step_up=True)
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
    if repo.active_signature(me()) is None:
        return err("No tiene firma escaneada registrada: el Administrador del Sistema debe cargarla en «Usuarios › Firmas» "
                   "antes de que usted apruebe el informe", 409)

    conflict = _transition(
        rep, "GERENCIA", "APPROVE_JEFE", delegation=acting_delegation("JEFE", a.get("audit_domain", "GENERAL")),
        approved_by=None, approved_at=None, approved_body_sha256=None,
        jefe_approved_by=me(), jefe_approved_at="now",
        jefe_approved_body_sha256=rep["body_sha256"],
    )
    if conflict:
        return conflict
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
    delegation = acting_delegation("GERENCIA" if role == "GERENTE_CI" else "CONTRALOR")
    signer_name = (repo.user_brief(me()) or {}).get("name") or g.claims.get("username", me())
    reason = f"Informe de auditoría {a['code']} - {label}"   # guion simple: la fuente del sello no tiene «—»
    try:
        if delegation:
            # El suplente firma con su propio certificado, en nombre del titular.
            signer = _personal_signer(required=True)
            signer_name = f"{signer_name} (suplente de {delegation['titular_name']})"
            reason += f" - por suplencia de {delegation['titular_name']}"
        else:
            # Quien tiene certificado propio firma con él; si no, con el institucional del rol,
            # siempre que no esté a nombre de otra persona (p. ej. un Gerente que ya se retiró).
            signer = _personal_signer(required=False) or _role_signer(cfg, role, label)
        scanned = repo.active_signature(me())
        if scanned is None:
            raise SignerCertificateError("No tiene firma escaneada registrada: el Administrador del Sistema debe cargarla "
                                         "en «Usuarios › Firmas» antes de que usted firme")
    except SignerCertificateError as ex:
        log("AUDIT_REPORT_SIGN_REJECTED", outcome="DENIED", entity_type="audit_report", entity_id=str(rid),
            metadata={"role": role, "reason": str(ex)}, request_id=g.request_id)
        return err(str(ex), 409)
    except Exception as ex:  # noqa: BLE001 - certificado institucional ausente o ilegible
        log("AUDIT_REPORT_SIGN_FAILED", outcome="FAILURE", entity_type="audit_report", entity_id=str(rid),
            metadata={"role": role, "error": type(ex).__name__}, request_id=g.request_id)
        return err("No fue posible cargar el certificado de firma" + (f" ({ex})" if cfg.get("ENV") == "dev" else ""), 500)
    try:
        signed = signing.sign_pdf(
            base, signer,
            reason=reason,
            location=cfg.get("SIGNING_LOCATION", "Venezuela"),
            signer_name=signer_name,
            field_name=field, box=box, tsa_url=cfg.get("TSA_URL"),
            signature_image=scanned["content"],
        )
        key = f"reports/{rid}/v{version}/{uuid.uuid4()}.pdf"
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

    if role == "GERENTE_CI":
        # Aprobar y firmar en una sola transición. El paso siguiente es Contraloría.
        new_status, action = "CONTRALOR", "APPROVE_SIGN_GERENTE"
        approval = dict(
            gerente_approved_by=me(), gerente_approved_at="now",
            gerente_approved_body_sha256=rep["body_sha256"],
        )
    else:
        new_status, action = "SIGNED", "APPROVE_SIGN_CONTRALOR"
        approval = dict(
            contralor_approved_by=me(), contralor_approved_at="now",
            contralor_approved_body_sha256=rep["body_sha256"],
            approved_by=me(), approved_at="now",
            approved_body_sha256=rep["body_sha256"],
        )

    # El registro del PDF firmado y el cambio de estado se confirman juntos:
    # si el informe cambió mientras se firmaba, no queda ninguno de los dos.
    try:
        conflict = _transition(
            rep, new_status, action, delegation=delegation,
            signed_doc={"role": role, "version": version, "signed": signed, "key": key},
            **approval,
        )
    except Exception as ex:  # noqa: BLE001
        log(
            "AUDIT_REPORT_SIGN_REGISTRATION_FAILED",
            outcome="FAILURE",
            entity_type="audit_report",
            entity_id=str(rid),
            metadata={"role": role, "error": type(ex).__name__, "object_key": key},
            request_id=g.request_id,
        )
        return err(
            "El documento firmado se almacenó, pero no pudo registrarse. "
            "Requiere revisión antes de reintentar.",
            500,
        )
    if conflict:
        # El PDF ya está en el almacenamiento inmutable; se deja constancia para conciliarlo.
        log(
            "AUDIT_REPORT_SIGNED_PDF_UNREGISTERED", outcome="FAILURE",
            entity_type="audit_report", entity_id=str(rid),
            metadata={"role": role, "object_key": key, "reason": "STALE_REPORT_STATE"},
            request_id=g.request_id,
        )
        return conflict

    log(
        "AUDIT_REPORT_SIGNED", entity_type="audit_report",
        entity_id=str(rid),
        after_data={
            "role": role, "version": version,
            "sha256_signed": signed.sha256_signed,
            "cert_serial": signed.cert_serial,
            "delegation": delegation["id"] if delegation else None,
            "on_behalf_of": delegation["titular_id"] if delegation else None,
        },
        request_id=g.request_id,
    )
    notify_report_signed(str(rid), a, role, new_status, str(me()), getattr(g, "request_id", None))
    return jsonify(
        status=new_status, signed_by=role,
        timestamp_embedded=signed.timestamp_embedded,
    )


class SignerCertificateError(Exception):
    pass


def _norm_name(value):
    import unicodedata
    value = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(ch for ch in value if not unicodedata.combining(ch)).casefold().split())


def _personal_signer(required):
    """Firmante con el certificado propio del usuario, descifrado con el anillo de claves (aad = id del usuario)."""
    from app.core.security.crypto import CryptoError, KeyRing
    from app.modules.reporting.signing import service as signing

    cert = repo.signing_certificate(me())
    if cert is None:
        if required:
            raise SignerCertificateError("Como suplente debe firmar con su propio certificado: súbalo en «Suplencias › Mi certificado de firma»")
        return None
    if cert.get("not_after") and cert["not_after"] < datetime.now(timezone.utc):
        raise SignerCertificateError("Su certificado de firma está vencido; suba uno vigente en «Suplencias › Mi certificado de firma»")
    try:
        ring = KeyRing.from_env()
        aad = str(me()).encode()
        p12 = ring.decrypt(cert["p12_encrypted"], aad=aad)
        passphrase = ring.decrypt(cert["passphrase_encrypted"], aad=aad)
        return signing.load_signer_from_pkcs12(p12, passphrase)
    except (CryptoError, signing.SigningError, KeyError) as ex:
        current_app.logger.warning("No se pudo cargar el certificado personal: %s", type(ex).__name__)
        raise SignerCertificateError("No se pudo usar su certificado de firma; vuelva a subirlo") from ex


def _role_signer(cfg, role, label):
    """Certificado institucional del rol, salvo que pertenezca a otra persona registrada en SICAS.

    Nadie firma con el certificado de otro: si el titular del certificado es otro usuario (activo o
    dado de baja), quien firma debe registrar su certificado propio.
    """
    from app.modules.reporting.signing import service as signing

    signer = signing.load_signer(cfg, role)
    holder = _norm_name(signer.signing_cert.subject.native.get("common_name"))
    if holder:
        owner = next((u for u in repo.q("SELECT id::text, full_name FROM iam.users")
                      if _norm_name(u["full_name"]) == holder), None)
        if owner and owner["id"] != str(me()):
            raise SignerCertificateError(
                f"El certificado institucional de {label} está a nombre de {owner['full_name']}. Cada firmante usa su "
                "propio certificado: súbalo en «Suplencias › Mi certificado de firma» antes de firmar.")
    return signer


@bp.post("/reports/<uuid:rid>/sign/contralor")
@stage_required("audit:sign_contralor", step_up=True)
def sign_contralor(rid):
    return _sign(rid, "CONTRALOR")


@bp.post("/reports/<uuid:rid>/sign/gerente")
@stage_required("audit:sign_gerente", step_up=True)
def sign_gerente(rid):
    return _sign(rid, "GERENTE_CI")


@bp.get("/reports/<uuid:rid>/pdf")
@stage_required("audit:read", "audit:read_final")
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

    # El informe firmado debe seguir siendo elegible para enviar el PAC.
    # Se bloquea la auditoría sin aplicar la restricción genérica de escritura.
    if repo.lock_audit(a["id"]) is None:
        return err("No encontrada", 404)

    # Releer tras el bloqueo: otra petición pudo cerrar la auditoría mientras
    # esta petición esperaba adquirir la fila.
    a = repo.get_audit(a["id"])
    if a is None or not visible(a):
        return err("No encontrada", 404)

    if not repo.is_member(a["id"], me()):
        return err("Solo el equipo auditor envía el PAC", 403)
    if a["status"] != "IN_PROGRESS":
        return err("El PAC ya fue enviado y la auditoría está cerrada", 409)
    # El PAC acompaña a la última versión del informe final, que debe estar firmada
    # (una versión reabierta y aún en preparación no permite enviarlo).
    finals = [r for r in repo.reports(a["id"]) if r["kind"] == "FINAL"]
    final = finals[0] if finals and finals[0]["status"] == "SIGNED" else None
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
    snapshot = _phase_snapshot(a, "PAC_SENT", report=final, reason=f"PAC enviado a {to}")
    _change(a, "audit", a["id"], "PAC_SENT", {"to": to, "status": {"before": a.get("status"), "after": "CLOSED"}}, report=final)
    repo.mark_pac_sent(a["id"], to, me(), phase_snapshot=snapshot)
    log("PAC_SENT", entity_type="audit", entity_id=a["id"], after_data={"to": to, "emailed": emailed}, request_id=g.request_id)
    return jsonify(status="CLOSED", emailed=emailed, note=None if emailed else "Registrado como enviado y auditoría cerrada. Entregue el informe firmado y el PAC a la unidad (el correo automático no está configurado).")


@bp.get("/final-reports")
@stage_required(
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


# ------------------------------------------------------------------ suplencias: administración
AUTHORIZER_PERMS = ("audit:report_approve", "audit:report_approve_gerente")


def _delegation_view(d):
    open_ = d["revoked_at"] is None and d["ends_on"] >= date.today()
    return {**d, "stage_label": STAGE_LABEL.get(d["stage"], d["stage"]),
            "can_revoke": open_ and (STAGE_AUTHORIZER[d["stage"]] in own_perms() or d["titular_id"] == me())}


@bp.get("/delegations")
@stage_required("audit:read", "audit:read_final", *AUTHORIZER_PERMS)
def delegations():
    """Suplencias: quien autoriza las ve todas; el resto, las suyas (como titular, suplente o autorizador)."""
    authorizer = bool(set(AUTHORIZER_PERMS) & own_perms())
    rows = repo.list_delegations(None if authorizer else me(), include_past=request.args.get("all") == "1")
    cert = repo.signing_certificate(me())
    return jsonify(
        delegations=[_delegation_view(d) for d in rows],
        can_authorize=sorted(st for st, p in STAGE_AUTHORIZER.items() if p in own_perms()),
        my_certificate=({k: cert[k] for k in ("subject", "serial", "not_after", "uploaded_at")} if cert else None),
        needs_certificate=_can_sign_reports(),
    )


@bp.get("/delegations/candidates")
@permission_required(*AUTHORIZER_PERMS)
def delegation_candidates():
    """Titulares y suplentes posibles por etapa, ya filtrados por segregación de funciones."""
    from app.core.security.permissions import ROLE_LABELS, permissions_for_roles
    out = {"JEFE_FINANCIERA": {"titulars": [], "delegates": []}, "JEFE_SISTEMAS": {"titulars": [], "delegates": []},
           "GERENCIA": {"titulars": [], "delegates": []}, "CONTRALOR": {"titulars": [], "delegates": []}}
    allowed = {st for st, p in STAGE_AUTHORIZER.items() if p in own_perms()}
    for u in repo.delegation_candidates():
        granted = permissions_for_roles(u["roles"])
        brief = {"id": u["id"], "name": u["name"], "username": u["username"],
                 "roles": [ROLE_LABELS.get(r, r) for r in u["roles"]]}
        for key, stage, domain in (("JEFE_FINANCIERA", "JEFE", "FINANCIERA"), ("JEFE_SISTEMAS", "JEFE", "SISTEMAS"),
                                   ("GERENCIA", "GERENCIA", None), ("CONTRALOR", "CONTRALOR", None)):
            if stage not in allowed:
                continue
            if holds_stage(granted, stage, domain):
                out[key]["titulars"].append(brief)
            elif _delegate_problem(u, granted, stage, domain) is None and u["id"] != me():
                out[key]["delegates"].append(brief)
    return jsonify(candidates={k: v for k, v in out.items() if v["titulars"] or v["delegates"]})


def _delegate_problem(user, granted, stage, domain):
    """Motivo por el que el usuario no puede ser suplente de la etapa, o None."""
    from app.core.security.permissions import SYS_ADMIN
    if SYS_ADMIN in (user.get("roles") or []):
        return "El Administrador del Sistema no participa en el flujo del informe"
    if holds_stage(granted, stage, domain):
        return "Esa persona ya cumple esa función con sus propios roles"
    if stage == "JEFE" and not ({"audit:financial_read"} if domain == "FINANCIERA" else {"audit:systems_read"}) <= granted:
        return "El suplente del Jefe de Auditoría debe pertenecer al mismo dominio de auditoría"
    v = sod_conflicts(granted | stage_perms(stage, domain))
    if v:
        return "Segregación de funciones: " + "; ".join(why for _, _, why in v)
    return None


@bp.post("/delegations")
@permission_required(*AUTHORIZER_PERMS, step_up=True)
def new_delegation():
    """Suplencia temporal (máximo 90 días). Jefe y Gerencia los autoriza el Contralor; al Contralor, Gerencia."""
    from app.core.security.permissions import permissions_for_roles
    d = request.get_json(silent=True) or {}
    stage = str(d.get("stage") or "").upper()
    if stage not in STAGE_PERMS:
        return err("Etapa inválida: JEFE, GERENCIA o CONTRALOR")
    if STAGE_AUTHORIZER[stage] not in own_perms():
        return err(f"La suplencia de {STAGE_LABEL[stage]} la autoriza "
                   + ("Gerencia" if stage == "CONTRALOR" else "el Contralor"), 403)
    domain = str(d.get("audit_domain") or "").upper() or None
    if stage == "JEFE":
        if domain not in DOMAIN_REVIEW:
            return err("Indique el dominio del Jefe de Auditoría: FINANCIERA o SISTEMAS")
    else:
        domain = None
    try:
        starts_on = parse_date(d.get("starts_on"), "Desde", required=True)
        ends_on = parse_date(d.get("ends_on"), "Hasta", required=True)
        reason = txt(d, "reason", 10, 1000)
    except ValueError as ex:
        return err(str(ex))
    if starts_on < date.today():
        return err("La suplencia no puede comenzar en una fecha pasada")
    if ends_on < starts_on or (ends_on - starts_on).days > MAX_DELEGATION_DAYS:
        return err(f"El plazo debe ser de 0 a {MAX_DELEGATION_DAYS} días")
    titular = repo.user_brief(str(d.get("titular_id") or "")) if _is_uuid(d.get("titular_id")) else None
    delegate = repo.user_brief(str(d.get("delegate_id") or "")) if _is_uuid(d.get("delegate_id")) else None
    if titular is None or delegate is None:
        return err("Titular o suplente no encontrado", 404)
    if titular["id"] == delegate["id"]:
        return err("El suplente debe ser distinto del titular")
    if delegate["id"] == me():
        return err("No puede autorizarse a sí mismo como suplente", 403)
    if not delegate["is_active"] or delegate["removed_at"]:
        return err("El suplente debe tener una cuenta activa")
    if not holds_stage(permissions_for_roles(titular["roles"]), stage, domain):
        return err(f"El titular indicado no cumple la función de {STAGE_LABEL[stage]}" + (f" de {domain.title()}" if domain else ""))
    problem = _delegate_problem(delegate, permissions_for_roles(delegate["roles"]), stage, domain)
    if problem:
        return err(problem, 409)
    if repo.overlapping_delegation(stage, domain, titular["id"], starts_on, ends_on):
        return err("Ese titular ya tiene una suplencia vigente que se superpone con esas fechas; revóquela primero", 409)
    did = repo.create_delegation({"stage": stage, "audit_domain": domain, "titular_id": titular["id"],
                                  "delegate_id": delegate["id"], "starts_on": starts_on, "ends_on": ends_on,
                                  "reason": reason}, me())
    log("DELEGATION_CREATED", entity_type="delegation", entity_id=did,
        after_data={"stage": stage, "domain": domain, "titular": titular["id"], "delegate": delegate["id"],
                    "starts_on": starts_on.isoformat(), "ends_on": ends_on.isoformat(), "reason": reason},
        request_id=g.request_id)
    return jsonify(id=did, note=f"{delegate['name']} actuará como {STAGE_LABEL[stage]} en nombre de {titular['name']} "
                                f"del {starts_on.isoformat()} al {ends_on.isoformat()}."), 201


def _is_uuid(v):
    try:
        uuid.UUID(str(v))
        return True
    except (TypeError, ValueError):
        return False


@bp.post("/delegations/<uuid:did>/revoke")
@stage_required("audit:read", "audit:read_final", *AUTHORIZER_PERMS, step_up=True)
def revoke_delegation(did):
    """La revoca quien puede autorizarla o el propio titular (por ejemplo, al regresar antes de lo previsto)."""
    dl = repo.get_delegation(did)
    if dl is None:
        return err("Suplencia no encontrada", 404)
    if not (STAGE_AUTHORIZER[dl["stage"]] in own_perms() or dl["titular_id"] == me()):
        return err("Solo el titular o quien autoriza esa etapa puede revocar la suplencia", 403)
    try:
        reason = txt(request.get_json(silent=True) or {}, "reason", 5, 500)
    except ValueError as ex:
        return err(str(ex))
    if not repo.revoke_delegation(did, me(), reason):
        return err("La suplencia ya estaba revocada", 409)
    log("DELEGATION_REVOKED", entity_type="delegation", entity_id=str(did), after_data={"reason": reason}, request_id=g.request_id)
    return jsonify(status="REVOKED")


MAX_CERT_BYTES = 200 * 1024


def _can_sign_reports():
    """Firma informes por su rol o tiene una suplencia (vigente o programada) de Gerencia o del Contralor."""
    if {"audit:sign_gerente", "audit:sign_contralor"} & own_perms():
        return True
    return any(dl["delegate_id"] == me() and dl["stage"] in ("GERENCIA", "CONTRALOR") for dl in repo.list_delegations(me()))


@bp.post("/signing-certificate")
@stage_required("audit:read", "audit:read_final", step_up=True)
def upload_signing_certificate():
    """Certificado propio (.p12/.pfx) del suplente de Gerencia o del Contralor; se guarda cifrado (AES-256-GCM)."""
    from app.core.security.crypto import CryptoError, KeyRing
    from app.modules.reporting.signing import service as signing

    if not _can_sign_reports():
        return err("Solo quienes firman informes (Gerencia, Contralor o sus suplentes) registran su certificado de firma", 403)
    f = request.files.get("file")
    passphrase = (request.form.get("passphrase") or "").encode()
    if f is None or not (f.filename or "").lower().endswith((".p12", ".pfx")):
        return err("Adjunte el certificado en formato .p12 o .pfx")
    data = f.read(MAX_CERT_BYTES + 1)
    if not data or len(data) > MAX_CERT_BYTES:
        return err("El certificado debe pesar como máximo 200 KB")
    try:
        info = signing.certificate_info(signing.load_signer_from_pkcs12(data, passphrase))
    except signing.SigningError as ex:
        return err(str(ex))
    if info["not_after"] and info["not_after"] < datetime.now(timezone.utc):
        return err("El certificado está vencido")
    try:
        ring = KeyRing.from_env()
        aad = str(me()).encode()
        repo.save_signing_certificate(me(), ring.encrypt(data, aad=aad), ring.encrypt(passphrase, aad=aad), info)
    except CryptoError:
        current_app.logger.exception("Anillo de claves no disponible para cifrar el certificado")
        return err("El servidor no tiene configurado el cifrado de certificados; avise al Administrador del Sistema", 503)
    log("SIGNING_CERTIFICATE_UPLOADED", entity_type="user", entity_id=str(me()),
        after_data={"subject": info["subject"], "serial": info["serial"],
                    "not_after": info["not_after"].isoformat() if info["not_after"] else None}, request_id=g.request_id)
    return jsonify(subject=info["subject"], serial=info["serial"], not_after=info["not_after"])
