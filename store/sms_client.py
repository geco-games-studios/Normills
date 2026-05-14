import logging
from django.conf import settings
import requests

logger = logging.getLogger(__name__)

EXCITESMS_HTTP_SEND_URL = "https://gateway.excitesms.com/api/v3/sms/send"

class SMSClient:
    def __init__(self, api_token=None, sender_id=None, request_timeout=10):
        self.api_token = api_token or getattr(settings, 'EXCITESMS_API_TOKEN', None)
        self.sender_id = sender_id or getattr(settings, 'EXCITESMS_SENDER_ID', 'GecoGames')
        self.timeout = request_timeout

        if not self.api_token:
            raise ValueError('ExciteSMS API token is required. Set EXCITESMS_API_TOKEN in settings.')

    def send_sms(self, recipient, message, sms_type='plain', schedule_time=None, dlt_template_id=None):
        payload = {
            'recipient': recipient,
            'sender_id': self.sender_id,
            'type': sms_type,
            'message': message,
        }

        if schedule_time:
            payload['schedule_time'] = schedule_time
        if dlt_template_id:
            payload['dlt_template_id'] = dlt_template_id

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_token}',
        }

        try:
            response = requests.post(
                EXCITESMS_HTTP_SEND_URL,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.exception('ExciteSMS request failed for recipient=%s', recipient)
            raise

        try:
            data = response.json()
        except ValueError:
            logger.error('ExciteSMS response was not valid JSON: %s', response.text)
            raise

        if data.get('status') != 'success':
            error_message = data.get('message', response.text)
            logger.error('ExciteSMS returned error: %s', error_message)
            raise Exception(f'ExciteSMS error: {error_message}')

        logger.info('ExciteSMS SMS sent successfully to %s', recipient)
        return data
