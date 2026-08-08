"""
Fast2SMS wrapper. route="q" needs no DLT setup — fine to start with;
switch to "dlt" (with an approved sender_id + template) for production.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

FAST2SMS_BULK_URL = "https://www.fast2sms.com/dev/bulkV2"


def send_sms(to: str, message: str) -> None:
    number = to.lstrip("+")
    if number.startswith("91") and len(number) == 12:
        number = number[2:]

    payload = {
        "route": getattr(settings, "FAST2SMS_ROUTE", "q"),
        "message": message,
        "language": "english",
        "flash": 0,
        "numbers": number,
    }
    if payload["route"] == "dlt":
        payload["sender_id"] = settings.FAST2SMS_SENDER_ID

    try:
        response = requests.post(
            FAST2SMS_BULK_URL,
            headers={"authorization": settings.FAST2SMS_AUTH_KEY},
            data=payload,
            timeout=10,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        logger.exception("Fast2SMS send failed")
        return

    if not data.get("return"):
        logger.error("Fast2SMS send failed: %s", data)