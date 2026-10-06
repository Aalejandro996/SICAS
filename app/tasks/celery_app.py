from celery import Celery


def make_celery(app) -> Celery:
    celery = Celery(app.import_name, broker=app.config["CELERY_BROKER_URL"],
                    backend=app.config["CELERY_RESULT_BACKEND"])
    celery.conf.update(
        task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
        imports=("app.tasks.ingestion_tasks", "app.tasks.audit_tasks", "app.tasks.alert_tasks", "app.tasks.admin_tasks"),
        task_serializer="json", accept_content=["json"], result_expires=86400,
        task_routes={
            "app.tasks.ingestion_tasks.*": {"queue": "ingestion"},
            "app.tasks.audit_tasks.*": {"queue": "ingestion"},
            "app.tasks.alert_tasks.*": {"queue": "alerts"},
        },
        beat_schedule={
            "verificar-cadena-audit-trail": {"task": "app.tasks.audit_tasks.verify_audit_chain",
                                             "schedule": 3600.0},
            "particiones-audit-trail": {"task": "app.tasks.audit_tasks.ensure_audit_partitions", "schedule": 86400.0},
            "anclar-cadena-audit-trail": {"task": "app.tasks.audit_tasks.anchor_audit_chain", "schedule": 21600.0},
        },
    )

    class ContextTask(celery.Task):
        def __call__(self, *a, **kw):
            with app.app_context():
                return self.run(*a, **kw)

    celery.Task = ContextTask
    if app.config.get("CELERY_EAGER"):        # desarrollo sin worker: las tareas corren dentro de la petición
        celery.conf.task_always_eager = True
        celery.conf.task_eager_propagates = False
    app.extensions["celery"] = celery
    return celery
