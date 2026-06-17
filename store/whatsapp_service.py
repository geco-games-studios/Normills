import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _clean_whatsapp_number(value):
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('0') and len(digits) == 10:
        digits = '260' + digits[1:]
    elif len(digits) == 9:
        digits = '260' + digits
    return digits


def build_admin_order_receipt(order):
    items = "\n".join(
        f"- {item.product.name} x{item.quantity} @ K{item.price}"
        for item in order.items.select_related('product').all()
    )
    return (
        f"New Normils order #{order.id}\n"
        f"Customer: {order.first_name} {order.last_name}\n"
        f"Phone: {order.phone or 'Not provided'}\n"
        f"Fulfilment: {order.get_delivery_method_display()}\n"
        f"Payment: {order.get_payment_method_display()} / {order.get_payment_status_display()}\n"
        f"Total: K{order.total}\n\n"
        f"Items:\n{items}\n\n"
        f"Dashboard search: #{order.id}"
    )


def send_admin_whatsapp_order_receipt(order):
    admin_number = _clean_whatsapp_number(getattr(settings, 'ADMIN_WHATSAPP_NUMBER', ''))
    token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '')
    phone_number_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')

    if not admin_number or not token or not phone_number_id:
        logger.warning(
            'WhatsApp order receipt skipped for order %s: ADMIN_WHATSAPP_NUMBER, '
            'WHATSAPP_ACCESS_TOKEN, or WHATSAPP_PHONE_NUMBER_ID is missing.',
            order.id,
        )
        return {'status': 'skipped', 'message': 'WhatsApp Business API is not configured.'}

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        'messaging_product': 'whatsapp',
        'to': admin_number,
        'type': 'text',
        'text': {
            'preview_url': False,
            'body': build_admin_order_receipt(order),
        },
    }
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        logger.info('WhatsApp order receipt sent for order %s to %s', order.id, admin_number)
        return {'status': 'sent', 'response': response.json()}
    except Exception as exc:
        logger.exception('WhatsApp order receipt failed for order %s', order.id)
        return {'status': 'failed', 'message': str(exc)}
