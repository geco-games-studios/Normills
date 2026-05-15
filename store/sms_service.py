import logging
from django.conf import settings
from users.models import User
from manager.models import Store
from .models import Order
from .sms_client import SMSClient

logger = logging.getLogger(__name__)

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
    if order.store and order.store.owner:
        store_owner = order.store.owner
        numbers = []
        if hasattr(store_owner, 'phone_number') and store_owner.phone_number:
            numbers.append(store_owner.phone_number)
        if hasattr(store_owner, 'alt_phone_number') and store_owner.alt_phone_number:
            numbers.append(store_owner.alt_phone_number)
        
        for num in numbers:
            owner_message = (
                f"New Order Received!\n"
                f"Order Number: {order.id}\n"
                f"Customer: {order.first_name} {order.last_name}\n"
                f"Phone: {order.phone}\n"
                f"Product(s): {', '.join([item.product.name for item in order.items.all()])}\n"
                f"Total: {order.total}"
            )
            
            try:
                result = sms_client.send_sms(num, owner_message)
                if result.get('status') == 'skipped':
                    logger.warning('Store owner SMS skipped for order %s to %s: %s', order.id, num, result.get('message'))
                else:
                    logger.info('Store owner SMS sent for order %s to %s', order.id, num)
            except Exception as e:
                logger.exception('Store owner SMS failed for order %s to %s', order.id, num)
    else:
        logger.warning('Order %s has no associated store or store owner', order.id)
