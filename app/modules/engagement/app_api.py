"""Rutas de la auditoría de aplicativos (inventario, encuestas direccionadas, pruebas técnicas, riesgos, madurez)
y de la retroalimentación del motor de reglas (decisiones del auditor, sugerencias, propuestas y normativa)."""
from __future__ import annotations

import hashlib
import re
import uuid

from flask import Response, current_app, g, jsonify, request

from app.core.audit.audit_service import audit as log
from app.core.security.rbac import permission_required

from . import api as eng
from . import app_audit as ap
from . import app_repo as arepo
from . import app_survey as sv
from . import evidence_rules, learning, norms, storage
from . import repositories as repo
from .api import bp, err, me, perms

INVENTORY_MANAGE = ("audit:systems_review", "audit:unit_manage")
ENGINE_READ = ("rule:configure", "audit:systems_review", "audit:financial_review", "audit:report_approve")


def _survey_key() -> bytes:
    return hashlib.sha256(b"sicas-encuesta|" + current_app.config["SECRET_KEY"].encode()).digest()


def is_app_audit(a) -> bool:
    return str(a.get("audit_kind") or "").upper() == "APLICATIVO"


def app_criteria(template_code: str) -> list[dict]:
    """Controles de la plantilla con los pesos aprobados por el Contralor (reglas WEIGHT vigentes)."""
    rules = arepo.active_rules_map()
    weights = {t.split(":", 1)[1]: int(v.get("weight", 1)) for (k, t), v in rules.items()
               if k == "WEIGHT" and t.startswith(f"{template_code}:")}
    return ap.criteria(template_code, weights)


# ------------------------------------------------------------------ inventario de aplicativos
def _profile(d: dict) -> tuple[dict, dict]:
    prof = {}
    for k in ("vendor", "product", "version", "db_engine", "hosting", "custodian"):
        v = str(d.get(k) or "").strip()
        prof[k] = v[:160] or None
    prof["modules"] = str(d.get("modules") or "").strip()[:2000] or None
    prof["interfaces"] = str(d.get("interfaces") or "").strip()[:2000] or None
    prof["category"] = str(d.get("category") or "CORE").upper()
    prof["model"] = str(d.get("model") or "TERCERIZADO").upper()
    prof["criticality"] = str(d.get("criticality") or "ALTA").upper()
    prof["template_code"] = str(d.get("template_code") or "ACSELX").upper()
    if not prof["product"]:
        raise ValueError("Indique el producto (por ejemplo, Acsel/x)")
    if prof["category"] not in ap.CATEGORIES or prof["model"] not in ap.MODELS or prof["criticality"] not in ap.CRITICALITY:
        raise ValueError("Categoría, modelo o criticidad inválidos")
    if prof["template_code"] not in ap.TEMPLATES:
        raise ValueError("Plantilla de auditoría inexistente")
    try:
        prof["users_count"] = None if d.get("users_count") in (None, "") else int(d["users_count"])
        prof["owner_unit_id"] = None if d.get("owner_unit_id") in (None, "") else int(d["owner_unit_id"])
    except (TypeError, ValueError) as ex:
        raise ValueError("Usuarios y unidad dueña deben ser números") from ex
    if prof["users_count"] is not None and prof["users_count"] < 0:
        raise ValueError("Número de usuarios inválido")
    if prof["owner_unit_id"] is not None:
        u = repo.get_unit(prof["owner_unit_id"])
        if u is None or u["kind"] == "APLICATIVO":
            raise ValueError("La unidad dueña del proceso debe ser una unidad o sucursal existente")
    params = {}
    for k in ap.DEFAULT_PARAMS:
        v = (d.get("params") or {}).get(k, ap.DEFAULT_PARAMS[k])
        try:
            n = float(v)
        except (TypeError, ValueError) as ex:
            raise ValueError(f"{ap.PARAM_LABEL[k]}: indique un número") from ex
        if not 0 < n <= 10000:
            raise ValueError(f"{ap.PARAM_LABEL[k]}: valor fuera de rango")
        params[k] = int(n) if n.is_integer() else n
    return prof, params


@bp.get("/app-catalog")
@permission_required("audit:read", "audit:manage")
def app_catalog():
    return jsonify(areas=ap.AREAS, blocks=ap.BLOCKS, categories=ap.CATEGORIES, models=ap.MODELS, criticality=ap.CRITICALITY,
                   templates=ap.TEMPLATE_LABEL, params=ap.DEFAULT_PARAMS, param_labels=ap.PARAM_LABEL,
                   test_results=ap.TEST_RESULTS, maturity_names=ap.MATURITY_NAMES,
                   can_manage=bool(set(INVENTORY_MANAGE) & perms()))


@bp.get("/applications")
@permission_required("audit:systems_read", "audit:systems_review", "audit:unit_manage", "audit:report_approve")
def list_applications():
    return jsonify(applications=arepo.applications(), units=[u for u in repo.list_units() if u["kind"] != "APLICATIVO"])


@bp.post("/applications")
@permission_required(*INVENTORY_MANAGE)
def new_application():
    d = request.get_json(silent=True) or {}
    code, name = str(d.get("code", "")).strip().upper(), str(d.get("name", "")).strip()
    if not re.fullmatch(r"[A-Z0-9-]{2,20}", code) or not 3 <= len(name) <= 120:
        return err("Código (2-20 letras, números o guiones) y nombre (3-120 caracteres) son obligatorios")
    try:
        prof, params = _profile(d)
    except ValueError as ex:
        return err(str(ex))
    try:
        uid_ = arepo.create_application(code, name, prof, params, me(), str(d.get("responsible_name") or "").strip()[:200] or None,
                                        str(d.get("responsible_role") or "").strip()[:200] or None)
    except Exception:  # noqa: BLE001 - código repetido
        repo.db.session.rollback()
        return err("Ya existe una unidad o aplicativo con ese código", 409)
    log("APPLICATION_CREATED", entity_type="application", entity_id=str(uid_), after_data={"code": code, **prof, "params": params},
        request_id=g.request_id)
    return jsonify(id=uid_), 201


@bp.put("/applications/<int:uid_>")
@permission_required(*INVENTORY_MANAGE)
def edit_application(uid_):
    before = arepo.application(uid_)
    if before is None:
        return err("Aplicativo inexistente", 404)
    d = request.get_json(silent=True) or {}
    name = str(d.get("name") or before["name"]).strip()
    if not 3 <= len(name) <= 120:
        return err("Nombre: 3 a 120 caracteres")
    try:
        prof, params = _profile({**before, **d})
    except ValueError as ex:
        return err(str(ex))
    arepo.update_application(uid_, name, prof, params, me(), str(d.get("responsible_name", before.get("responsible_name")) or "").strip()[:200] or None,
                             str(d.get("responsible_role", before.get("responsible_role")) or "").strip()[:200] or None,
                             active=d.get("active", before["active"]))
    log("APPLICATION_UPDATED", entity_type="application", entity_id=str(uid_),
        before_data={k: before.get(k) for k in (*arepo.PROFILE_FIELDS, "params")}, after_data={**prof, "params": params},
        request_id=g.request_id)
    return jsonify(status="OK")


# ------------------------------------------------------------------ auditoría del aplicativo
def _load_app(aid, write=False):
    a, e = eng.load(aid, write=write, phases="WORK" if write else None)
    if e:
        return None, None, None, e
    if not is_app_audit(a):
        return None, None, None, err("Disponible solo para auditorías de aplicativos", 400)
    app = arepo.application_for_audit(a["id"])
    ws = next((w for w in repo.worksheets_with_items(a["id"]) if w["kind"] == "SISTEMAS"), None)
    if app is None or ws is None:
        return None, None, None, err("La auditoría no tiene ficha de aplicativo o cuestionario", 409)
    return a, app, ws, None


def app_state(a, app, ws) -> dict:
    """Todo lo que muestra la pestaña Aplicativo y el informe (cálculos en servidor)."""
    code = app["template_code"]
    params = ap.params_of(app)
    crit = ws["criteria"]
    history = learning.history_adjustments(arepo.control_history(a["id"]))
    risks = ap.risk_matrix(code, ws["items"], history, arepo.risk_overrides(a["id"]))
    blocks = ap.block_summary(crit, ws["items"])
    ov = ap.overview(crit, ws["items"], params)
    tests = ap.tests_view(code, arepo.tests(a["id"]))
    mat = ap.maturity(code, crit, ws["items"], arepo.maturity_overrides(a["id"]))
    key, label = ap.opinion(ov, risks)
    surveys = arepo.surveys(a["id"])
    last = {}
    for s in surveys:
        last.setdefault(s["area"], s)
    areas = [{**x, "last_survey": last.get(x["area"])} for x in ap.areas_in(crit)]
    return {"application": {**app, "params": params, "template_title": ap.TEMPLATE_LABEL.get(code, code)},
            "overview": ov, "blocks": blocks, "risks": risks, "maturity": mat, "trace": ap.traceability(code, ws["items"]),
            "tests": tests, "tests_summary": ap.tests_summary(tests), "areas": areas, "surveys": surveys,
            "opinion": {"key": key, "label": label, "text": ap.opinion_text(app["name"], ov, risks, blocks)},
            "history": history, "worksheet_id": ws["id"]}


def report_section(a) -> dict | None:
    """Sección del aplicativo dentro del cuerpo del informe (queda dentro del SHA-256 que se aprueba)."""
    app = arepo.application_for_audit(a["id"])
    ws = next((w for w in repo.worksheets_with_items(a["id"]) if w["kind"] == "SISTEMAS"), None)
    if app is None or ws is None:
        return None
    st = app_state(a, app, ws)
    keep = ("vendor", "product", "version", "category", "model", "db_engine", "hosting", "criticality", "owner_unit_name",
            "custodian", "users_count", "template_title", "name")
    return {"profile": {k: st["application"].get(k) for k in keep}, "params": st["application"]["params"],
            "overview": {k: v for k, v in st["overview"].items() if k != "areas"}, "blocks": st["blocks"],
            "risks": [{k: r[k] for k in ("code", "category", "control", "probability", "impact", "score", "level", "status",
                                         "history_reason")} | {"override_reason": (r.get("override") or {}).get("reason")}
                      for r in st["risks"]],
            "maturity": [{k: m[k] for k in ("key", "label", "level", "name", "state", "note", "suggested")} for m in st["maturity"]],
            "trace": st["trace"], "tests": [{k: t[k] for k in ("code", "program", "area", "result", "detail", "standard")} for t in st["tests"]],
            "tests_summary": st["tests_summary"], "opinion": st["opinion"],
            "surveys": [{k: x[k] for k in ("area", "respondent_name", "respondent_role", "answered_on", "rows_applied")} for x in st["surveys"]]}


@bp.get("/<uuid:aid>/application")
@permission_required("audit:read", "audit:read_final")
def audit_application(aid):
    a, app, ws, e = _load_app(aid)
    if e:
        return e
    editable = repo.is_member(a["id"], me()) and a["status"] == "IN_PROGRESS" and not eng.final_locked(a["id"])
    return jsonify(**app_state(a, app, ws), editable=editable, phase=a["phase"],
                   can_survey=editable and a["phase"] == "LEVANTAMIENTO")


@bp.get("/<uuid:aid>/application/survey/<area>")
@permission_required("audit:read")
def download_survey(aid, area):
    a, app, ws, e = _load_app(aid)
    if e:
        return e
    if area not in ap.AREAS:
        return err("Área inexistente", 404)
    try:
        data = sv.build({"id": a["id"], "code": a["code"]}, app, area, ws["criteria"], ws["items"], ap.params_of(app), _survey_key(),
                        (g.claims or {}).get("username") or "auditor")
    except sv.SurveyError as ex:
        return err(str(ex))
    log("APP_SURVEY_EXPORTED", entity_type="audit", entity_id=a["id"], after_data={"area": area}, request_id=g.request_id)
    name = f"Encuesta_{a['code']}_{area}.xlsx"
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@bp.post("/<uuid:aid>/application/survey")
@permission_required("audit:manage")
def upload_survey(aid):
    """Aplica una encuesta devuelta por un área al Levantamiento (solo sus preguntas) y la guarda como evidencia."""
    a, app, ws, e = _load_app(aid, write=True)
    if e:
        return e
    if a["phase"] != "LEVANTAMIENTO":
        return err("Las encuestas se cargan en la fase de Levantamiento", 409)
    f = request.files.get("file")
    if f is None:
        return err("Adjunte la encuesta en Excel")
    data = f.read(sv.MAX_BYTES + 1)
    try:
        parsed = sv.parse(data, _survey_key(), a["id"], ws["criteria"])
    except sv.SurveyError as ex:
        return err(str(ex))
    if not parsed["answers"]:
        return err("La encuesta no tiene respuestas")
    by_ref = {it["ref"]: it for it in ws["items"]}
    resp = parsed["respondent"]
    applied = 0
    for code, res in parsed["answers"].items():
        it = by_ref.get(code)
        if it is None:
            continue
        res = {**res, "fuente": {"area": parsed["area"], "respondent": resp.get("name"), "role": resp.get("role"),
                                 "date": resp.get("date").isoformat() if resp.get("date") else None}}
        before = (it.get("results") or {}).get(code)
        if before == res:
            continue
        eng._change(a, "item", it["id"], "ITEM_UPDATED_SURVEY", {"results": {"before": before, "after": res}},
                    reason=f"Encuesta direccionada de {ap.AREAS[parsed['area']]}" + (f" respondida por {resp['name']}" if resp.get("name") else ""))
        repo.update_item(it["id"], {code: res}, it.get("observation"), it.get("info_exception"),
                         ap.control_points(res), me())
        applied += 1
    try:
        name, ctype = evidence_rules.check(f.filename or "encuesta.xlsx", data)
    except evidence_rules.EvidenceError:
        name, ctype = "encuesta.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    sha = hashlib.sha256(data).hexdigest()
    eid_ = str(uuid.uuid4())
    key = f"evidence/{a['id']}/{eid_}"
    storage.put(key, data)
    eng._change(a, "evidence", eid_, "EVIDENCE_ADDED", {"filename": name, "sha256": sha, "survey_area": parsed["area"]})
    eid = repo.add_evidence(a["id"], None, None, name, ctype, len(data), sha, key,
                            f"Encuesta direccionada — {ap.AREAS[parsed['area']]}", me())
    arepo.add_survey(a["id"], parsed["area"], resp, name, sha, applied, eid, me())
    repo.db.session.commit()
    log("APP_SURVEY_IMPORTED", entity_type="audit", entity_id=a["id"],
        after_data={"area": parsed["area"], "applied": applied, "respondent": resp.get("name"), "sha256": sha}, request_id=g.request_id)
    return jsonify(applied=applied, area=parsed["area"], area_label=ap.AREAS[parsed["area"]], problems=parsed["problems"],
                   respondent=resp)


@bp.put("/<uuid:aid>/application/tests/<code>")
@permission_required("audit:manage")
def save_app_test(aid, code):
    a, app, ws, e = _load_app(aid, write=True)
    if e:
        return e
    known = {t[0] for t in ap.template(app["template_code"])["tests"]}
    if code not in known:
        return err("Prueba inexistente", 404)
    d = request.get_json(silent=True) or {}
    result = str(d.get("result") or "").upper()
    if result not in ap.TEST_RESULTS:
        return err("Resultado: CUMPLE, NO_CUMPLE, NO_APLICA o PENDIENTE")
    detail = str(d.get("detail") or "").strip()[:3000] or None
    query_used = str(d.get("query_used") or "").strip()[:3000] or None
    if result == "NO_CUMPLE" and (not detail or len(detail) < 10):
        return err("Describa lo encontrado (mínimo 10 caracteres) cuando la prueba no cumple")
    ev = d.get("evidence_id") or None
    if ev:
        if not any(x["id"] == str(ev) for x in repo.evidence(a["id"])):
            return err("La evidencia debe pertenecer a esta auditoría", 400)
    before = arepo.tests(a["id"]).get(code)
    eng._change(a, "app_test", code, "APP_TEST_RECORDED",
                {"result": {"before": (before or {}).get("result"), "after": result}, "detail": detail})
    arepo.save_test(a["id"], code, result, detail, query_used, ev, me())
    repo.db.session.commit()
    log("APP_TEST_RECORDED", entity_type="audit", entity_id=a["id"], after_data={"code": code, "result": result}, request_id=g.request_id)
    return jsonify(status="OK")


@bp.put("/<uuid:aid>/application/risks/<code>")
@permission_required("audit:manage")
def override_risk(aid, code):
    a, app, ws, e = _load_app(aid, write=True)
    if e:
        return e
    if code not in {r[0] for r in ap.template(app["template_code"])["risks"]}:
        return err("Riesgo inexistente", 404)
    d = request.get_json(silent=True) or {}
    current = {r["code"]: r for r in app_state(a, app, ws)["risks"]}[code]
    if d.get("clear"):
        eng._change(a, "app_risk", code, "APP_RISK_RESTORED", {"override": current.get("override")},
                    reason="Se vuelve a la probabilidad e impacto calculados")
        arepo.save_risk_override(a["id"], code, None, None, None, me())
        repo.db.session.commit()
        return jsonify(status="OK")
    try:
        p, i = int(d.get("probability")), int(d.get("impact"))
    except (TypeError, ValueError):
        return err("Probabilidad e impacto: números del 1 al 5")
    reason = str(d.get("reason") or "").strip()[:1000]
    if not (1 <= p <= 5 and 1 <= i <= 5):
        return err("Probabilidad e impacto: números del 1 al 5")
    if len(reason) < 10:
        return err("Indique el motivo del ajuste (mínimo 10 caracteres)")
    before = {"probability": current["probability"], "impact": current["impact"], "level": current["level"]}
    after = {"probability": p, "impact": i, "level": ap.risk_level(p * i)}
    eng._change(a, "app_risk", code, "APP_RISK_OVERRIDDEN", {"before": before, "after": after}, reason=reason)
    arepo.save_risk_override(a["id"], code, p, i, reason, me())
    arepo.add_feedback("RISK_MATRIX_OVERRIDE", me(), a["id"], pattern_key=f"ctrl:{current['control']}",
                       controls=[current["control"]], before=before, after=after, reason=reason)
    repo.db.session.commit()
    log("APP_RISK_OVERRIDDEN", entity_type="audit", entity_id=a["id"], before_data=before, after_data={"code": code, **after},
        request_id=g.request_id)
    return jsonify(status="OK")


@bp.put("/<uuid:aid>/application/maturity/<key>")
@permission_required("audit:manage")
def override_maturity(aid, key):
    a, app, ws, e = _load_app(aid, write=True)
    if e:
        return e
    if key not in {m[0] for m in ap.template(app["template_code"])["maturity"]}:
        return err("Dominio inexistente", 404)
    d = request.get_json(silent=True) or {}
    current = {m["key"]: m for m in app_state(a, app, ws)["maturity"]}[key]
    if d.get("clear"):
        eng._change(a, "app_maturity", key, "APP_MATURITY_RESTORED", {"override": current.get("override")})
        arepo.save_maturity(a["id"], key, None, None, me())
        repo.db.session.commit()
        return jsonify(status="OK")
    try:
        level = int(d.get("level"))
    except (TypeError, ValueError):
        return err("Nivel de madurez: 0 a 5")
    note = str(d.get("note") or "").strip()[:2000]
    if not 0 <= level <= 5:
        return err("Nivel de madurez: 0 a 5")
    if len(note) < 10:
        return err("Redacte el dictamen técnico del dominio (mínimo 10 caracteres)")
    eng._change(a, "app_maturity", key, "APP_MATURITY_SET", {"before": current.get("level"), "after": level, "note": note})
    arepo.save_maturity(a["id"], key, level, note, me())
    if current.get("suggested") is not None and current["suggested"] != level:
        arepo.add_feedback("MATURITY_OVERRIDE", me(), a["id"], pattern_key=f"madurez:{key}",
                           before={"level": current["suggested"]}, after={"level": level}, reason=note)
    repo.db.session.commit()
    log("APP_MATURITY_SET", entity_type="audit", entity_id=a["id"], after_data={"key": key, "level": level}, request_id=g.request_id)
    return jsonify(status="OK")


# ------------------------------------------------------------------ retroalimentación sobre los hallazgos
def _obs_for_feedback(oid):
    o = repo.get_observation(oid)
    if o is None:
        return None, None, err("No encontrada", 404)
    a, e = eng.load(o["audit_id"], write=True, phases="WORK")
    if e:
        return None, None, e
    if o.get("origin") != "AUTO":
        return None, None, err("Solo los hallazgos redactados por el motor se aceptan o descartan", 409)
    return o, a, None


def _controls_of(o) -> list[str]:
    codes = re.findall(r"\b([A-Z]{2,4}\d{2,3})\b", f"{o.get('title') or ''} {o.get('recommendation') or ''}")
    return list(dict.fromkeys(codes))[:20]


@bp.post("/observations/<uuid:oid>/accept")
@permission_required("audit:manage")
def accept_observation(oid):
    o, a, e = _obs_for_feedback(oid)
    if e:
        return e
    if o.get("accepted_at"):
        return jsonify(status="OK", note="Ya estaba aceptado")
    eng._change(a, "observation", str(oid), "OBSERVATION_ACCEPTED", {}, reason="El auditor acepta la redacción del motor")
    arepo.mark_accepted(oid, me())
    arepo.add_feedback("OBS_ACCEPTED", me(), a["id"], oid, learning.pattern_key(o.get("rule_key"), _controls_of(o)), _controls_of(o),
                       after={"risk": o["risk"]})
    repo.db.session.commit()
    log("OBSERVATION_ACCEPTED", entity_type="observation", entity_id=str(oid), request_id=g.request_id)
    return jsonify(status="OK")


@bp.post("/observations/<uuid:oid>/discard")
@permission_required("audit:manage")
def discard_observation(oid):
    o, a, e = _obs_for_feedback(oid)
    if e:
        return e
    if o.get("unit_decision") or o.get("pac_action"):
        return err("El hallazgo ya tiene respuesta de la unidad o acción del PAC: no se puede descartar", 409)
    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()[:1000]
    if len(reason) < 10:
        return err("Indique por qué descarta el hallazgo (mínimo 10 caracteres)")
    eng._change(a, "observation", str(oid), "OBSERVATION_DISCARDED", {"title": o["title"], "risk": o["risk"]}, reason=reason)
    arepo.mark_discarded(oid, me(), reason)
    arepo.add_feedback("OBS_DISCARDED", me(), a["id"], oid, learning.pattern_key(o.get("rule_key"), _controls_of(o)), _controls_of(o),
                       before={"title": o["title"], "risk": o["risk"]}, reason=reason)
    repo.db.session.commit()
    log("OBSERVATION_DISCARDED", entity_type="observation", entity_id=str(oid), after_data={"reason": reason}, request_id=g.request_id)
    return jsonify(status="OK")


def record_edit_feedback(a, o, upd, reason):
    """Llamado al editar una observación: registra la decisión del auditor sobre un hallazgo del motor."""
    if o.get("origin") != "AUTO":
        return
    key = learning.pattern_key(o.get("rule_key"), _controls_of(o))
    ctrls = _controls_of(o)
    if "risk" in upd and upd["risk"] != o.get("risk"):
        arepo.add_feedback("RISK_CHANGED", me(), a["id"], o["id"], key, ctrls, before={"risk": o.get("risk")},
                           after={"risk": upd["risk"]}, reason=reason)
    changed = [k for k in learning.FINDING_FIELDS if k in upd and upd[k] != o.get(k)]
    if changed:
        arepo.add_feedback("OBS_EDITED", me(), a["id"], o["id"], key, ctrls, before={k: o.get(k) for k in changed},
                           after={k: upd[k] for k in changed}, reason=reason)


@bp.get("/observations/<uuid:oid>/suggestions")
@permission_required("audit:manage", "audit:read")
def observation_suggestions(oid):
    o = repo.get_observation(oid)
    if o is None:
        return err("No encontrada", 404)
    a, e = eng.load(o["audit_id"])
    if e:
        return e
    target = {**o, "controls": _controls_of(o)}
    return jsonify(suggestions=learning.suggestions(target, arepo.approved_observations(a["id"])))


@bp.post("/<uuid:aid>/observation-suggestions")
@permission_required("audit:manage")
def draft_suggestions(aid):
    """Sugerencias para una observación que se está redactando (título y condición aún sin guardar)."""
    a, e = eng.load(aid)
    if e:
        return e
    d = request.get_json(silent=True) or {}
    target = {"title": str(d.get("title") or "")[:300], "condition": str(d.get("condition") or "")[:3000]}
    if len(target["title"] + target["condition"]) < 15:
        return jsonify(suggestions=[])
    return jsonify(suggestions=learning.suggestions(target, arepo.approved_observations(a["id"])))


# ------------------------------------------------------------------ motor: retroalimentación, propuestas y reglas
@bp.get("/engine/feedback")
@permission_required(*ENGINE_READ)
def engine_feedback():
    events = arepo.feedback(500)
    for e in events:
        e["pattern_label"] = learning.pattern_label(e.get("pattern_key")) if e.get("pattern_key") else None
    return jsonify(summary=learning.feedback_summary(events), events=events[:100], kinds=learning.FEEDBACK_KINDS)


def analyze_patterns() -> int:
    fb = arepo.feedback(5000)
    hist = arepo.control_history()
    rules = arepo.active_rules_map()
    weights = {t: int(v.get("weight", 1)) for (k, t), v in rules.items() if k == "WEIGHT"}
    created = 0
    for p in learning.propose(fb, hist, weights, arepo.open_targets()):
        arepo.add_proposal(p)
        created += 1
    repo.db.session.commit()
    return created


@bp.post("/engine/analyze")
@permission_required(*ENGINE_READ)
def engine_analyze():
    n = analyze_patterns()
    if n:
        log("ENGINE_PROPOSALS_CREATED", entity_type="engine", entity_id="proposals", after_data={"created": n}, request_id=g.request_id)
    return jsonify(created=n)


@bp.get("/engine/proposals")
@permission_required(*ENGINE_READ)
def engine_proposals():
    props, rules_ = arepo.proposals(), arepo.rules(False)
    for x in props + rules_:
        x["target_label"] = learning.pattern_label(x["target"]) if x["kind"] != "WEIGHT" else f"Control {x['target'].replace(':', ' · ')}"
    return jsonify(proposals=props, rules=rules_, kinds=learning.PROPOSAL_KINDS,
                   can_decide="rule:configure" in perms())


@bp.post("/engine/proposals/<uuid:pid>/decide")
@permission_required("rule:configure", step_up=True)
def engine_decide(pid):
    p = arepo.get_proposal(pid)
    if p is None:
        return err("Propuesta inexistente", 404)
    if p["status"] != "PROPUESTA":
        return err("La propuesta ya fue decidida", 409)
    d = request.get_json(silent=True) or {}
    decision = str(d.get("decision") or "").upper()
    note = str(d.get("note") or "").strip()[:2000]
    if decision not in ("APROBADA", "RECHAZADA"):
        return err("Decisión: APROBADA o RECHAZADA")
    if len(note) < 10:
        return err("Indique el fundamento de la decisión (mínimo 10 caracteres)")
    arepo.decide_proposal(pid, decision, note, me())
    rid = arepo.activate_rule(p, me()) if decision == "APROBADA" else None
    repo.db.session.commit()
    log("ENGINE_PROPOSAL_" + decision, entity_type="engine_proposal", entity_id=str(pid),
        before_data={"kind": p["kind"], "target": p["target"], "value": p["value"], "evidence": p["evidence"]},
        after_data={"decision": decision, "note": note, "rule_id": rid}, request_id=g.request_id)
    return jsonify(status="OK", rule_id=rid)


@bp.post("/engine/rules/<uuid:rid>/retire")
@permission_required("rule:configure", step_up=True)
def engine_retire(rid):
    note = str((request.get_json(silent=True) or {}).get("note") or "").strip()[:2000]
    if len(note) < 10:
        return err("Indique el motivo del retiro (mínimo 10 caracteres)")
    arepo.retire_rule(rid, me())
    repo.db.session.commit()
    log("ENGINE_RULE_RETIRED", entity_type="engine_rule", entity_id=str(rid), after_data={"note": note}, request_id=g.request_id)
    return jsonify(status="OK")


@bp.get("/norms")
@permission_required("audit:read", "audit:manage", *ENGINE_READ)
def list_norms():
    rows = arepo.norms() or norms.as_dicts()
    return jsonify(norms=rows, sources=norms.SOURCES, can_edit="rule:configure" in perms())


@bp.put("/norms/<code>")
@permission_required("rule:configure")
def edit_norm(code):
    before = arepo.norms_map().get(code)
    if before is None:
        return err("Norma inexistente", 404)
    d = request.get_json(silent=True) or {}
    status = str(d.get("status") or before["status"]).upper()
    summary = str(d.get("summary") if d.get("summary") is not None else before.get("summary") or "").strip()[:2000] or None
    if status not in ("VIGENTE", "POR_VALIDAR", "DEROGADA"):
        return err("Estado: VIGENTE, POR_VALIDAR o DEROGADA")
    arepo.update_norm(code, status, summary, me())
    repo.db.session.commit()
    log("NORM_UPDATED", entity_type="norm", entity_id=code, before_data={"status": before["status"], "summary": before.get("summary")},
        after_data={"status": status, "summary": summary}, request_id=g.request_id)
    return jsonify(status="OK")
