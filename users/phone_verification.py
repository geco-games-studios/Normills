import logging
import random
from datetime import timedelta

from django.utils import timezone

from store.sms_client import SMSClient

from .models import PhoneOTP


logger = logging.getLogger(__name__)


def normalize_phone(phone):
    if not phone or not isinstance(phone, str):
        return ''
    digits = ''.join(ch for ch in phone if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('0') and len(digits) == 10:
        digits = '260' + digits[1:]
    elif len(digits) == 9 and not digits.startswith('0'):
        digits = '260' + digits
    if len(digits) < 12 or not digits.isdigit():
        return ''
    return digits


def send_phone_verification_code(user, phone=None):
    phone = normalize_phone(phone or getattr(getattr(user, 'client_profile', None), 'phone_number', ''))
    if not phone:
        return False, 'Please add a valid phone number before verification.'

    code = f"{random.randint(100000, 999999)}"
    expires = timezone.now() + timedelta(minutes=10)
    PhoneOTP.objects.create(user=user, phone=phone, code=code, expires_at=expires)

    try:
        result = SMSClient().send_sms(phone, f"Your Normils verification code is {code}")
        logger.info('OTP SMS send result for user=%s phone=%s: %s', user.id, phone, result)
        if isinstance(result, dict) and result.get('status') != 'success':
            return False, result.get('message', 'SMS send failed')
    except Exception as exc:
        logger.exception('Failed to send OTP SMS for user %s: %s', user.id, exc)
        return False, 'We were unable to send the verification SMS. Please check your phone number and try again.'

    return True, 'A verification code has been sent to your phone.'
