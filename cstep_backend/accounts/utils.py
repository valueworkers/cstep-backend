import random
import logging

import requests
from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)

FAST2SMS_SEND_URL = "https://www.fast2sms.com/dev/otp/send"
OTP_CACHE_TTL = 300 

class Fast2SMSError(Exception):
    pass


class Fast2SMSService:

    @staticmethod
    def _cache_key(identifier: str) -> str:
        return f"otp:{identifier}"

    @staticmethod
    def send_otp(mobile: str) -> None:
 
        otp = f"{random.randint(100000, 999999)}"
        key = Fast2SMSService._cache_key(mobile)
        cache.set(key, otp, OTP_CACHE_TTL)

        headers = {
            "authorization": settings.FAST2SMS_AUTH_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "mobile": mobile,
            "otp_id": settings.FAST2SMS_OTP_ID,
            "otp_expiry": OTP_CACHE_TTL // 60,  # minutes
            "otp_length": 6,
            "otp": otp,
        }

        try:
            response = requests.post(FAST2SMS_SEND_URL, json=payload, headers=headers, timeout=10)
            data = response.json()
        except requests.RequestException:
            logger.exception("Fast2SMS send OTP request failed")
            cache.delete(key)
            raise Fast2SMSError("Unable to send OTP")
        except ValueError:
            logger.error("Fast2SMS send OTP returned non-JSON response: %s", response.text)
            cache.delete(key)
            raise Fast2SMSError("Unable to send OTP")

        if not data.get("return"):
            cache.delete(key)
            raise Fast2SMSError(data.get("message", ["Failed to send OTP"])[0] if isinstance(data.get("message"), list) else data.get("message", "Failed to send OTP"))

    @staticmethod
    def verify_otp(mobile: str, otp: str) -> bool:
        key = Fast2SMSService._cache_key(mobile)
        cached_otp = cache.get(key)

        if cached_otp is None:
            raise ValidationError("OTP expired or not found. Please request a new one.")
        if cached_otp != otp:
            raise ValidationError("Invalid OTP.")

        cache.delete(key)
        return True