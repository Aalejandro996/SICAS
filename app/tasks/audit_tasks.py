from celery import shared_task
from sqlalchemy import text

from app.core.audit.audit_service import audit
from app.extensions import db
from app.modules.audit_engine import repositories as repo
from app.modules.audit_engine.context import SqlContext
from app.modules.audit_engine.engine import by_severity, run_engine


@shared_task(bind=True, acks_late=True, max_retries=2, retry_backoff=True)
def run_anomaly_rules(self, job_id: str | None = None, triggered_by: str | None = None):
    """Ejecuta el motor sobre una carga (o sobre todo si job_id es None) y persiste hallazgos deduplicados."""
    params, disabled = repo.load_params(db.session)
    enabled = None
    if disabled:
        from app.modules.audit_engine.engine import REGISTRY
        enabled = set(REGISTRY) - disabled

    result = run_engine(SqlContext(db.engine, job_id), params, enabled)
    run_id = repo.start_run(db.session, job_id, triggered_by, result.params_snapshot)
    inserted = repo.save_findings(db.session, run_id, result.findings)
    repo.finish_run(db.session, run_id, "COMPLETED_WITH_ERRORS" if result.errors else "COMPLETED")
    db.session.commit()

    sev = by_severity(result.findings)
    audit(action="ENGINE_RUN_COMPLETED", entity_type="engine_run", entity_id=run_id,
          after_data={"nuevos": inserted, "por_severidad": sev, "errores": result.errors})
    if sev["CRITICAL"] or sev["HIGH"]:
        from app.tasks.alert_tasks import notify_findings
        notify_findings.apply_async(args=[run_id], queue="alerts")
    return {"run_id": run_id, "new_findings": inserted, "by_severity": sev}


@shared_task
def verify_audit_chain(from_id: int = 0):
    """
    1) Recalcula cada hash y el encadenamiento en la base (audit.verify_chain).
    2) Contrasta TODOS los anclajes firmados: firma válida y fila/hash presentes (detecta borrado de cola).
    Ante cualquier problema registra AUDIT_INTEGRITY_FAILURE para que Kibana/alertas lo detecten.
    """
    import os

    from app.core.integrity.checkpoint import Checkpoint, check_against_log, load_public_key, verify_checkpoint

    problems = [{"id": r.broken_id, "motivo": r.reason}
                for r in db.session.execute(text("SELECT broken_id, reason FROM audit.verify_chain(:f)"), {"f": from_id})]
    pub_path = os.environ.get("SICAS_CHECKPOINT_PUB_PEM")
    if pub_path:
        pub = load_public_key(pub_path)
        for cp in db.session.execute(text("SELECT created_at, last_audit_id, last_hash, key_id, signature "
                                          "FROM audit.chain_checkpoints ORDER BY id")).all():
            c = Checkpoint(cp.created_at, cp.last_audit_id, bytes(cp.last_hash).hex(), cp.key_id, bytes(cp.signature))
            if not verify_checkpoint(pub, c):
                problems.append({"id": cp.last_audit_id, "motivo": "FIRMA_DE_ANCLAJE_INVALIDA"})
                continue
            row = db.session.execute(text("SELECT row_hash FROM audit.audit_log WHERE id=:i ORDER BY occurred_at DESC LIMIT 1"),
                                     {"i": cp.last_audit_id}).first()
            issue = check_against_log(c, bytes(row.row_hash).hex() if row else None)
            if issue:
                problems.append({"id": cp.last_audit_id, "motivo": issue})
    if problems:
        audit(action="AUDIT_INTEGRITY_FAILURE", outcome="FAILURE", metadata={"problemas": problems[:50], "total": len(problems)})
    return {"problems": len(problems)}


@shared_task
def anchor_audit_chain():
    """Firma y registra el estado actual de la cadena (último id y hash). Exportar además a almacenamiento WORM."""
    import os
    from datetime import datetime, timezone

    from app.core.integrity.checkpoint import create_checkpoint, load_private_key

    head = db.session.execute(text("SELECT id, row_hash FROM audit.audit_log ORDER BY id DESC LIMIT 1")).first()
    if head is None:
        return {"anchored": False}
    key_id = os.environ.get("SICAS_CHECKPOINT_KEY_ID", "cp1")
    cp = create_checkpoint(load_private_key(os.environ["SICAS_CHECKPOINT_KEY_PEM"]), key_id, head.id,
                           bytes(head.row_hash).hex(), datetime.now(timezone.utc))
    db.session.execute(text("INSERT INTO audit.chain_checkpoints (created_at, last_audit_id, last_hash, key_id, signature) "
                            "VALUES (:t, :i, :h, :k, :s)"),
                       {"t": cp.created_at, "i": cp.last_audit_id, "h": bytes.fromhex(cp.last_hash_hex), "k": key_id, "s": cp.signature})
    db.session.commit()
    return {"anchored": True, "last_audit_id": cp.last_audit_id}


@shared_task
def ensure_audit_partitions():
    """Crea las particiones mensuales del audit trail con 3 meses de anticipación."""
    n = db.session.execute(text("SELECT audit.ensure_partitions(3)")).scalar_one()
    db.session.commit()
    return {"created": n}
