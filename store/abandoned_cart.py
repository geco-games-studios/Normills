"""
Abandoned Cart Recovery System
--------------------------------
Tracks abandoned carts and sends automated recovery reminders
via SMS and/or email to bring customers back.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import send_mail

from store.models import Cart
from users.models import User
from store.sms_client import SMSClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class AbandonedCartRecord(models.Model):
    """
    Tracks a cart that was abandoned (items added but no checkout completed
    within a configurable timeframe).
    """

    cart = models.OneToOneField(Cart, on_delete=models.CASCADE, related_name='abandoned_record')
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='abandoned_carts'
    )
    session_id = models.CharField(max_length=100, blank=True)
    cart_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    item_count = models.PositiveIntegerField(default=0)
    first_reminder_sent = models.BooleanField(default=False)
    second_reminder_sent = models.BooleanField(default=False)
    final_reminder_sent = models.BooleanField(default=False)
    recovered = models.BooleanField(default=False)
    recovery_order = models.ForeignKey(
        'store.Order', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='abandoned_recovery'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Abandoned Cart'
        verbose_name_plural = 'Abandoned Carts'

    def __str__(self):
        owner = self.user.username if self.user else (self.session_id or 'Anonymous')
        return f'Abandoned Cart #{self.cart.id} — {owner} — K{self.cart_total}'


# ---------------------------------------------------------------------------
# Business Logic
# ---------------------------------------------------------------------------

# Configuration (can be overridden in settings.py)
def _abandon_timeout_minutes():
    """How many minutes of inactivity before a cart is considered abandoned."""
    return int(getattr(settings, 'ABANDON_TIMEOUT_MINUTES', '60'))


def _reminder_intervals():
    """
    Returns a list of (interval_hours, reminder_field) tuples.
    These define when each reminder is sent after abandonment.
    """
    return [
        (int(getattr(settings, 'FIRST_REMINDER_HOURS', '2')), 'first_reminder_sent'),
        (int(getattr(settings, 'SECOND_REMINDER_HOURS', '24')), 'second_reminder_sent'),
        (int(getattr(settings, 'FINAL_REMINDER_HOURS', '72')), 'final_reminder_sent'),
    ]


def flag_abandoned_carts():
    """
    Scans all carts that haven't been updated in X minutes,
    and have items but no order linked, and marks them as abandoned.
    Should be called periodically (e.g. via cron or management command).
    """
    timeout = _abandon_timeout_minutes()
    cutoff = timezone.now() - timedelta(minutes=timeout)

    # Carts with items that haven't been updated recently
    stale_carts = Cart.objects.filter(
        items__isnull=False,
        updated_at__lte=cutoff,
    ).distinct()

    marked = 0
    for cart in stale_carts:
        # Skip if already recorded
        if hasattr(cart, 'abandoned_record'):
            continue

        # Determine user / session
        user = cart.user
        session_id = cart.session_id or ''

        # Only track if we can reach the customer (authenticated or with session)
        if not user and not session_id:
            continue

        AbandonedCartRecord.objects.create(
            cart=cart,
            user=user,
            session_id=session_id,
            cart_total=cart.total,
            item_count=cart.item_count,
        )
        marked += 1
        logger.info('Flagged cart #%s as abandoned (user=%s)', cart.id, user)

    return marked


def send_scheduled_reminders():
    """
    Iterates over abandoned cart records and sends due reminders.
    Should be called periodically (e.g. via cron or management command).
    """
    sent = 0
    reminders = _reminder_intervals()

    for record in AbandonedCartRecord.objects.filter(recovered=False):
        if not record.cart.items.exists():
            continue  # Cart was emptied

        elapsed = timezone.now() - record.updated_at
        user_contact = _get_user_contact(record)

        if not user_contact:
            continue

        for hours, field_name in reminders:
            if getattr(record, field_name):
                continue  # Already sent this reminder

            if elapsed >= timedelta(hours=hours):
                # Send the reminder
                _send_reminder(record, user_contact, hours)
                setattr(record, field_name, True)
                record.save(update_fields=[field_name, 'updated_at'])
                sent += 1
                break  # Only send one reminder per cycle

    return sent


def _get_user_contact(record):
    """Get the best contact method for the user (phone or email)."""
    if record.user:
        phone = ''
        email = record.user.email
        try:
            phone = record.user.client_profile.phone_number
        except Exception:
            pass
        return {'phone': phone, 'email': email}

    # For anonymous users with session_id, we can't reach them directly
    return None


def _send_reminder(record, contact, hours_since):
    """Send a recovery reminder via SMS and/or email."""
    cart = record.cart
    items_summary = ', '.join(
        [f'{item.product.name} (x{item.quantity})' for item in cart.items.all()[:3]]
    )
    if cart.item_count > 3:
        items_summary += f' and {cart.item_count - 3} more items'

    # Build message
    if hours_since <= 4:
        message = (
            f"Hi! You left K{record.cart_total} worth of items in your cart at "
            f"Normills: {items_summary}. Complete your order now at "
            f"{getattr(settings, 'SITE_URL', 'https://normills.com')}/cart/"
        )
    elif hours_since <= 48:
        message = (
            f"Still thinking about it? Your cart with {items_summary} "
            f"(K{record.cart_total}) is waiting. Don't miss out! "
            f"{getattr(settings, 'SITE_URL', 'https://normills.com')}/cart/"
        )
    else:
        message = (
            f"Last chance! Your cart ({items_summary}) worth K{record.cart_total} "
            f"will expire soon. Complete your purchase now: "
            f"{getattr(settings, 'SITE_URL', 'https://normills.com')}/cart/"
        )

    # Send SMS
    if contact.get('phone'):
        try:
            sms_client = SMSClient()
            sms_client.send_sms(contact['phone'], message)
            logger.info(
                'Abandoned cart SMS sent to %s for cart #%s',
                contact['phone'], record.cart.id
            )
        except Exception as exc:
            logger.error(
                'Failed to send abandoned cart SMS for cart #%s: %s',
                record.cart.id, exc
            )

    # Send email
    if contact.get('email'):
        try:
            subject = 'You left items in your cart!'
            html_msg = render_to_string('emails/abandoned_cart.html', {
                'record': record,
                'cart': record.cart,
                'items_summary': items_summary,
            })
            plain_msg = strip_tags(html_msg)
            send_mail(
                subject, plain_msg,
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'hello@gecogames.com'),
                [contact['email']],
                html_message=html_msg,
                fail_silently=False,
            )
            logger.info(
                'Abandoned cart email sent to %s for cart #%s',
                contact['email'], record.cart.id
            )
        except Exception as exc:
            logger.error(
                'Failed to send abandoned cart email for cart #%s: %s',
                record.cart.id, exc
            )


def mark_recovered(record, order):
    """Mark an abandoned cart as recovered."""
    record.recovered = True
    record.recovery_order = order
    record.save(update_fields=['recovered', 'recovery_order', 'updated_at'])
    logger.info(
        'Abandoned cart #%s recovered via Order #%s',
        record.cart.id, order.id
    )