import logging
from django.conf import settings
from users.models import User
from manager.models import Store
from .models import Order
from .sms_client import SMSClient

logger = logging.getLogger(__name__)

def _get_store_owner_numbers(store):
    if not store or not getattr(store, 'owner', None):
        return []

    owner = store.owner
    numbers = []

    if hasattr(owner, 'phone_number') and owner.phone_number:
        numbers.append(owner.phone_number)
    if hasattr(owner, 'alt_phone_number') and owner.alt_phone_number:
        numbers.append(owner.alt_phone_number)
    if hasattr(owner, 'store_owner_profile'):
        profile = owner.store_owner_profile
        if profile and hasattr(profile, 'phone_number') and profile.phone_number:
            numbers.append(profile.phone_number)
        if profile and hasattr(profile, 'alt_phone_number') and profile.alt_phone_number:
            numbers.append(profile.alt_phone_number)

    seen = set()
    return [num for num in numbers if num and not (num in seen or seen.add(num))]


def send_order_sms(order: Order):
    """
    Send SMS to the user and store owner when an order is placed.
    """
    sms_client = SMSClient()
    
    # User SMS
    user_message = (
        f"Shipping Information\n"
        f"First Name\n{order.first_name}\n"
        f"Last Name\n{order.last_name}\n"
        f"Phone Number\n{order.phone}\n"
        f"Order Number: {order.id}\n"
        f"Product(s): {', '.join([item.product.name for item in order.items.all()])}\n"
        f"Total: {order.total}"
    )
    
    try:
        result = sms_client.send_sms(order.phone, user_message)
        if result.get('status') == 'skipped':
            logger.warning('User SMS skipped for order %s: %s', order.id, result.get('message'))
        else:
            logger.info('User SMS sent for order %s', order.id)
    except Exception as e:
        logger.exception('User SMS failed for order %s', order.id)

    # Store owner SMS (to two numbers)
    store = order.store
    if not store and order.items.exists():
        store = order.items.first().product.store

    numbers = _get_store_owner_numbers(store)
    if not numbers:
        logger.warning('Order %s store owner has no phone numbers configured', order.id)
        return

    logger.debug('Store owner SMS recipients for order %s: %s', order.id, numbers)

    owner_message = (
        f"New Order Received!\n"
        f"Order Number: {order.id}\n"
        f"Customer: {order.first_name} {order.last_name}\n"
        f"Phone: {order.phone}\n"
        f"Product(s): {', '.join([item.product.name for item in order.items.all()])}\n"
        f"Total: {order.total}"
    )

    for num in numbers:
        try:
            result = sms_client.send_sms(num, owner_message)
            if result.get('status') == 'skipped':
                logger.warning('Store owner SMS skipped for order %s to %s: %s', order.id, num, result.get('message'))
            else:
                logger.info('Store owner SMS sent for order %s to %s', order.id, num)
        except Exception as e:
            logger.exception('Store owner SMS failed for order %s to %s', order.id, num)


def send_order_receipt_sms(order: Order):
    """
    Send the same receipt SMS to the customer and all store owner numbers.
    """
    sms_client = SMSClient()
    receipt_message = (
        f"Receipt for Order #{order.id}\n. Thank you for shopping at Normis. "
        f"Customer: {order.first_name} {order.last_name}\n"
        f"Phone: {order.phone}\n"
        f"Product(s): {', '.join([item.product.name for item in order.items.all()])}\n"
        f"Total: {order.total}\n"
        f"Payment Method: {order.payment_method}\n"
        f"Status: {order.payment_status}"
    )

    store = order.store
    if not store and order.items.exists():
        store = order.items.first().product.store

    recipients = [order.phone] + _get_store_owner_numbers(store)
    seen = set()
    recipients = [num for num in recipients if num and not (num in seen or seen.add(num))]

    if not recipients:
        logger.warning('Receipt SMS for order %s has no valid recipients', order.id)
        return

    for recipient in recipients:
        try:
            result = sms_client.send_sms(recipient, receipt_message)
            if result.get('status') == 'skipped':
                logger.warning('Receipt SMS skipped for order %s to %s: %s', order.id, recipient, result.get('message'))
            else:
                logger.info('Receipt SMS sent for order %s to %s', order.id, recipient)
        except Exception:
            logger.exception('Receipt SMS failed for order %s to %s', order.id, recipient)
