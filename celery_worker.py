from app import create_app
from app.tasks.celery_app import make_celery

flask_app = create_app()
celery = make_celery(flask_app)
