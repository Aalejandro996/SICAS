import uuid

from flask import g

from app import create_app


def test_after_request_restores_missing_request_id():
    app = create_app()

    # Simula una respuesta cuyo ciclo perdió el atributo request_id.
    @app.before_request
    def remove_request_id_for_test():
        g.__dict__.pop("request_id", None)

    response = app.test_client().head("/__request_id_regression_test__")

    assert response.status_code < 500
    value = response.headers.get("X-Request-ID")
    assert value
    assert str(uuid.UUID(value)) == value
