# signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import EventDay

@receiver(post_save, sender=EventDay)
def resequence_after_save(sender, instance, created, **kwargs):
    EventDay.resequence(instance.event_id)


@receiver(post_delete, sender=EventDay)
def resequence_after_delete(sender, instance, **kwargs):
    EventDay.resequence(instance.event_id)
