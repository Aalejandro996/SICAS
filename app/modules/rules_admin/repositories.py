from __future__ import annotations

import json

from sqlalchemy import text

from app.extensions import db
from .service import ChangeRequest

_TABLE = {
    "SUDEASEG": ("engagement.regulatory_catalog", "topic"),
    "SISTEMAS": ("engagement.systems_rule_catalog", "domain_key"),
}


def _rows(sql, **params):
    return [dict(r._mapping) for r in db.session.execute(text(sql), params).all()]


class SqlRulesRepo:
    def current(self, engine, key):
        if engine == "UNIDAD":
            r = db.session.execute(text("SELECT name, kind, audit_domain, active, responsible_name, responsible_role "
                                        "FROM engagement.units WHERE code = :k"), {"k": key}).first()
            return dict(r._mapping) if r else None
        if engine == "CODIFICACION":
            cat, code = key.split(":", 1)
            r = db.session.execute(text("SELECT label, sort_order, active FROM engagement.codification_catalog "
                                        "WHERE catalog = :c AND code = :k"), {"c": cat, "k": code}).first()
            return dict(r._mapping) if r else None
        if engine == "ANALITICO":
            r = db.session.execute(text("SELECT params, enabled FROM engine.rule_parameters WHERE rule_code = :k"),
                                   {"k": key}).first()
            return dict(r._mapping) if r else None
        table, pk = _TABLE[engine]
        r = db.session.execute(text(f"SELECT * FROM {table} WHERE {pk} = :k"), {"k": key}).first()
        if r is None:
            return None
        row = dict(r._mapping)
        row["keywords"] = list(row.get("keywords") or [])
        return row

    def pending_exists(self, engine, key):
        return db.session.execute(text("SELECT 1 FROM engagement.rule_change_requests WHERE engine = :e AND rule_key = :k "
                                       "AND status = 'PENDING'"), {"e": engine, "k": key}).first() is not None

    def create_request(self, q: ChangeRequest):
        db.session.execute(text(
            "INSERT INTO engagement.rule_change_requests (id, engine, rule_key, payload, previous, reason, requested_by) "
            "VALUES (CAST(:i AS uuid), :e, :k, CAST(:p AS jsonb), CAST(:prev AS jsonb), :r, CAST(:u AS uuid))"),
            {"i": q.id, "e": q.engine, "k": q.rule_key, "p": json.dumps(q.payload, default=str),
             "prev": json.dumps(q.previous, default=str) if q.previous is not None else None, "r": q.reason, "u": q.requested_by})
        db.session.commit()

    def get_request(self, request_id):
        r = db.session.execute(text(
            "SELECT id::text, engine, rule_key, payload, previous, reason, requested_by::text, status "
            "FROM engagement.rule_change_requests WHERE id = CAST(:i AS uuid) FOR UPDATE"), {"i": request_id}).first()
        return ChangeRequest(r.id, r.engine, r.rule_key, r.payload, r.previous, r.reason, r.requested_by, r.status) if r else None

    def list_requests(self, status="PENDING"):
        return _rows(
            "SELECT q.id::text, q.engine, q.rule_key, q.payload, q.previous, q.reason, b.username AS requested_by, "
            "q.requested_by::text AS requested_by_id, q.status, q.created_at, d.username AS decided_by, q.decided_at, q.decision_note "
            "FROM engagement.rule_change_requests q JOIN iam.users b ON b.id = q.requested_by "
            "LEFT JOIN iam.users d ON d.id = q.decided_by WHERE q.status = :s ORDER BY q.created_at DESC LIMIT 200", s=status)

    def apply(self, engine, key, values, actor, is_new):
        if engine == "UNIDAD":
            if is_new:
                db.session.execute(text("INSERT INTO engagement.units (code, name, kind, audit_domain, active, responsible_name, "
                                        "responsible_role) VALUES (:k, :name, :kind, :audit_domain, :active, :responsible_name, "
                                        ":responsible_role)"), {"k": key, **values})
            else:
                db.session.execute(text("UPDATE engagement.units SET name = :name, kind = :kind, audit_domain = :audit_domain, "
                                        "active = :active, responsible_name = :responsible_name, responsible_role = :responsible_role "
                                        "WHERE code = :k"), {"k": key, **values})
            return
        if engine == "CODIFICACION":
            cat, code = key.split(":", 1)
            db.session.execute(text("INSERT INTO engagement.codification_catalog (catalog, code, label, sort_order, active, updated_by) "
                                    "VALUES (:c, :k, :label, :sort_order, :active, CAST(:u AS uuid)) ON CONFLICT (catalog, code) DO UPDATE "
                                    "SET label = EXCLUDED.label, sort_order = EXCLUDED.sort_order, active = EXCLUDED.active, "
                                    "updated_by = EXCLUDED.updated_by, updated_at = now()"),
                               {"c": cat, "k": code, "u": actor, **values})
            from app.modules.engagement import codification
            codification.invalidate()
            return
        if engine == "ANALITICO":
            db.session.execute(text(
                "INSERT INTO engine.rule_parameters (rule_code, params, enabled, updated_by) "
                "VALUES (:c, CAST(:p AS jsonb), :e, CAST(:u AS uuid)) ON CONFLICT (rule_code) DO UPDATE SET "
                "params = EXCLUDED.params, enabled = EXCLUDED.enabled, updated_by = EXCLUDED.updated_by, updated_at = now()"),
                {"c": key, "p": json.dumps(values["params"]), "e": values["enabled"], "u": actor})
            return
        table, pk = _TABLE[engine]
        cols = list(values)
        params = {c: values[c] for c in cols if c != "keywords"}
        params.update(kw=values["keywords"], k=key, u=actor)
        exprs = {c: ("CAST(:kw AS text[])" if c == "keywords" else f":{c}") for c in cols}
        if is_new:
            db.session.execute(text(
                f"INSERT INTO {table} ({pk}, {', '.join(cols)}, updated_by) "
                f"VALUES (:k, {', '.join(exprs[c] for c in cols)}, CAST(:u AS uuid))"), params)
        else:
            db.session.execute(text(
                f"UPDATE {table} SET " + ", ".join(f"{c} = {exprs[c]}" for c in cols)
                + f", updated_by = CAST(:u AS uuid), updated_at = now() WHERE {pk} = :k"), params)

    def decide(self, request_id, status, decided_by, note):
        db.session.execute(text(
            "UPDATE engagement.rule_change_requests SET status = :s, decided_by = CAST(:d AS uuid), decided_at = now(), "
            "decision_note = :n WHERE id = CAST(:i AS uuid)"), {"s": status, "d": decided_by, "n": note or None, "i": request_id})
        db.session.commit()                 # confirma también el cambio aplicado en la misma transacción

    def catalogs(self):
        from app.modules.audit_engine.engine import REGISTRY
        saved = {r["rule_code"]: r for r in _rows("SELECT rule_code, params, enabled, updated_at FROM engine.rule_parameters")}
        return {
            "unidades": _rows("SELECT code AS key, name AS label, kind, audit_domain, active, responsible_name, responsible_role "
                              "FROM engagement.units ORDER BY code"),
            "codificacion": _rows("SELECT catalog || ':' || code AS key, catalog, code, label, sort_order, active, updated_at "
                                  "FROM engagement.codification_catalog ORDER BY catalog, sort_order, code"),
            "sudeaseg": _rows("SELECT topic AS key, label, keywords, criteria, cause, effect, recommendation, sort_order, active, "
                              "updated_at FROM engagement.regulatory_catalog ORDER BY sort_order, topic"),
            "sistemas": _rows("SELECT domain_key AS key, label, keywords, criteria, cause, effect, recommendation, field_test, "
                              "critical, sort_order, active, updated_at FROM engagement.systems_rule_catalog ORDER BY sort_order, domain_key"),
            "analitico": [{"key": c, "title": cls.title, "defaults": cls.default_params,
                           "params": (saved.get(c) or {}).get("params") or {},
                           "enabled": (saved.get(c) or {}).get("enabled", True),
                           "updated_at": (saved.get(c) or {}).get("updated_at")} for c, cls in REGISTRY.items()],
        }
