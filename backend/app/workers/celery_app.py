from celery import Celery
from app.core.config import settings

celery = Celery(
    "twinmind",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery.conf.task_routes = {"app.workers.tasks.*": {"queue": "ingest"}}
