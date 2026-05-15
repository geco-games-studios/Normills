import logging
from django.conf import settings
import requests

logger = logging.getLogger(__name__)

EXCITESMS_HTTP_SEND_URL = "https://gateway.excitesms.com/api/http/sms/send"

class SMSClient:
    def __init__(self, api_token=None, sender_id=None, request_timeout=10):
        self.api_token = api_token or getattr(settings, 'EXCITESMS_API_TOKEN', '119|NKxrvTCsKex9LgFGPaZJfEVzyD2e44Vo8I0jpWZw65ec96a2')
        self.sender_id = sender_id or getattr(settings, 'EXCITESMS_SENDER_ID', 'GecoGames')
        self.timeout = request_timeout

        if not self.api_token:
            raise ValueError('ExciteSMS API token is required. Set EXCITESMS_API_TOKEN in settings.')

    def send_sms(self, recipient, message, sms_type='plain', schedule_time=None, dlt_template_id=None):
        # Format phone number - add Zambia country code if not present
        if recipient.startswith('0') and len(recipient) == 10:
            # Convert 0978516926 to 260978516926 (Zambia country code)
            recipient = '260' + recipient[1:]
        elif recipient.startswith('+'):
            # Remove + if present
            recipient = recipient[1:]
        
        payload = {
            'api_token': self.api_token,
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
        }

        try:
            response = requests.post(
                EXCITESMS_HTTP_SEND_URL,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.HTTPError as http_err:
            # Handle specific HTTP errors
            if response.status_code == 403:
                logger.warning('SMS service does not have permission for this region: %s', recipient)
                return {'status': 'skipped', 'message': 'Region not enabled for SMS'}
            elif response.status_code == 400:
                try:
                    error_data = response.json()
                    error_message = error_data.get('message', 'Bad Request')
                    if 'invalid phone number' in error_message.lower():
                        logger.warning('Invalid phone number format: %s', recipient)
                        return {'status': 'skipped', 'message': 'Invalid phone number'}
                except:
                    pass
            logger.exception('ExciteSMS HTTP error for recipient=%s: %s', recipient, http_err)
            raise
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
            
            # Check for specific error types
            if 'Permission to send an SMS has not been enabled' in error_message:
                logger.warning('SMS service does not have permission for this region. SMS not sent.')
                # Don't raise exception for permission issues - just log and continue
                return {'status': 'skipped', 'message': 'Region not enabled for SMS'}
            elif 'invalid phone number' in error_message:
                logger.warning('Invalid phone number format: %s', recipient)
                return {'status': 'skipped', 'message': 'Invalid phone number'}
            else:
                raise Exception(f'ExciteSMS error: {error_message}')

        logger.info('ExciteSMS SMS sent successfully to %s', recipient)
        return data
