import logging
import os
import smtplib
from email.message import EmailMessage

from celery import shared_task
from sqlalchemy import text

from app.extensions import db

log = logging.getLogger("alerts")

# Ruteo por regla -> destinatarios (configurable; ejemplo)
ROUTING = {
    "DUP-CLAIM": "siniestros@aseguradora.example",
    "DUP-POLICY": "suscripcion@aseguradora.example",
    "EARLY-CLAIM": "siniestros@aseguradora.example",
    "RESERVE-RANGE": "actuarial@aseguradora.example",
    "BENFORD-1D": "contraloria@aseguradora.example",
    "LCFT-THRESHOLD": "oficial.cumplimiento@aseguradora.example",
    "LCFT-STRUCTURING": "oficial.cumplimiento@aseguradora.example",
    "LCFT-WATCHLIST": "oficial.cumplimiento@aseguradora.example",
}


@shared_task(bind=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=3)
def notify_findings(self, run_id: str):
    rows = db.session.execute(text(
        "SELECT f.rule_code, o.severity, count(*) n "
        "FROM engine.finding_occurrences o "
        "JOIN engine.findings f ON f.id=o.finding_id "
        "WHERE o.run_id=CAST(:r AS uuid) "
        "AND o.severity IN ('HIGH','CRITICAL') AND o.is_new "
        "GROUP BY f.rule_code, o.severity"), {"r": run_id}).all()
    by_rule: dict[str, list] = {}
    for r in rows:
        by_rule.setdefault(r.rule_code, []).append(f"{r.severity}: {r.n}")
    custom = db.session.execute(text("SELECT value FROM admin.system_params WHERE key='alert_routing'")).scalar() or {}
    for rule, lines in by_rule.items():
        msg = EmailMessage()
        msg["Subject"] = f"[SICAS] Hallazgos {rule} pendientes de revisión"
        msg["From"], msg["To"] = os.environ.get("ALERT_FROM", "contraloria@aseguradora.example"), custom.get(rule) or ROUTING.get(rule, ROUTING["BENFORD-1D"])
        msg.set_content("Se generaron hallazgos de alta severidad.\n" + "\n".join(lines) +
                        "\nIngrese al sistema para revisarlos. (No se incluyen datos personales en este mensaje.)")
        with smtplib.SMTP(os.environ.get("SMTP_HOST", "localhost"), int(os.environ.get("SMTP_PORT", 25))) as s:
            s.send_message(msg)
        log.info("alerta enviada", extra={"rule": rule, "run_id": run_id})
