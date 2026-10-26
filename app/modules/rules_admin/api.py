import uuid

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.core.audit.audit_service import audit
from app.core.security.rbac import permission_required

from .repositories import SqlRulesRepo
from .service import RuleAdminError, RulesAdminService

bp = Blueprint("rules_admin", __name__)
_STATUS = {"NOT_FOUND": 404, "FORBIDDEN": 403, "DUAL_CONTROL": 403, "PENDING_EXISTS": 409, "NOT_PENDING": 409,
           "STALE": 409, "NO_CHANGE": 409}


def _analytic_defaults(code):
    from app.modules.audit_engine.engine import REGISTRY
    cls = REGISTRY.get(code)
    return dict(cls.default_params) if cls else None


def _svc() -> RulesAdminService:
    return RulesAdminService(SqlRulesRepo(), audit, lambda: str(uuid.uuid4()), _analytic_defaults)


def _guard(fn):
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except RuleAdminError as e:
            from app.extensions import db
            db.session.rollback()
            return jsonify(error=e.message, code=e.code), _STATUS.get(e.code, 400)
    wrapper.__name__ = fn.__name__
    return wrapper


@bp.get("/catalogs")
@permission_required("rule:propose", "rule:configure")
def catalogs():
    return jsonify(SqlRulesRepo().catalogs())


@bp.get("/requests")
@permission_required("rule:propose", "rule:configure")
def list_requests():
    status = request.args.get("status", "PENDING").upper()
    if status not in ("PENDING", "APPROVED", "REJECTED"):
        return jsonify(error="Estado inválido"), 400
    return jsonify(requests=SqlRulesRepo().list_requests(status))


@bp.post("/requests")
@permission_required("rule:propose", step_up=True)
@_guard
def propose():
    d = request.get_json(silent=True) or {}
    rid = _svc().propose(get_jwt_identity(), str(d.get("engine", "")), str(d.get("rule_key", "")).strip(),
                         d.get("payload"), str(d.get("reason", "")))
    return jsonify(request_id=rid, status="PENDING", note="El cambio queda pendiente de la aprobación del Contralor."), 201


@bp.post("/requests/<uuid:rid>/decision")
@permission_required("rule:configure", step_up=True)
@_guard
def decide(rid):
    d = request.get_json(silent=True) or {}
    status = _svc().decide(get_jwt_identity(), set(g.claims.get("perms", [])), str(rid), bool(d.get("approve")),
                           str(d.get("note", ""))[:1000])
    return jsonify(status=status)
