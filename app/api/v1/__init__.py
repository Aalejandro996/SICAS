def register_blueprints(app):
    from app.modules.admin.api import bp as admin_bp
    from app.modules.notifications.api import bp as notifications_bp
    from app.modules.analytics.api import bp as analytics_bp
    from app.modules.audit_engine.api import bp as engine_bp
    from app.modules.auditlog.api import bp as auditlog_bp
    from app.modules.auth.api import bp as auth_bp
    from app.modules.compliance.api import bp as compliance_bp
    from app.modules.engagement.api import bp as engagement_bp
    from app.modules.ingestion.api import bp as ingestion_bp
    from app.modules.reporting.api import bp as reporting_bp
    from .health import bp as health_bp

    p = "/api/v1"
    app.register_blueprint(health_bp, url_prefix=p)
    app.register_blueprint(auth_bp, url_prefix=f"{p}/auth")
    app.register_blueprint(admin_bp, url_prefix=f"{p}/admin")
    app.register_blueprint(notifications_bp, url_prefix=f"{p}/notifications")
    app.register_blueprint(ingestion_bp, url_prefix=f"{p}/ingestion")
    app.register_blueprint(engine_bp, url_prefix=f"{p}/engine")
    app.register_blueprint(compliance_bp, url_prefix=f"{p}/compliance")
    app.register_blueprint(reporting_bp, url_prefix=f"{p}/reports")
    app.register_blueprint(analytics_bp, url_prefix=f"{p}/analytics")
    app.register_blueprint(auditlog_bp, url_prefix=f"{p}/auditlog")
    app.register_blueprint(engagement_bp, url_prefix=f"{p}/audits")

    @app.get("/")
    def index():
        return app.send_static_file("index.html")
