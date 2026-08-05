# cstep_backend/celery.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cstep_backend.settings")

app = Celery("cstep_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.beat_schedule = {
    "push-live-analytics": {
        "task": "analytics.tasks.push_live_analytics",
        "schedule": 15.0,  # every 15 seconds
    }
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")