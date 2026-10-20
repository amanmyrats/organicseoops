import os
from logging.config import dictConfig

from celery import Celery
from celery.signals import setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("organicseoops")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@setup_logging.connect
def configure_worker_logging(**kwargs):
    from django.conf import settings

    dictConfig(settings.LOGGING)
