"""
Affiliate / Commission System
--------------------------------
- Affiliates earn commission on sales they refer.
- Commission rate is configurable per affiliate (default 10%).
- Tracks clicks, referrals, and payouts.
"""

import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone
from django.conf import settings

from store.models import Order, OrderItem, Product
from users.models import User

logger = logging.getLogger(__name__)

MONEY_PLACES = Decimal('0.01')


def _money(value):
    return Decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Affiliate(models.Model):
    """An affiliate marketer who refers customers."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='affiliate')
    referral_code = models.CharField(max_length=50, unique=True, blank=True)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal('0.10'),
        help_text='Commission rate as decimal (e.g. 0.10 = 10%)'
    )
    total_earned = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-total_earned']

    def __str__(self):
        return f'{self.user.username} ({self.referral_code}) — {self.commission_rate * 100}%'

    @property
    def balance(self):
        return _money(self.total_earned - self.total_paid)

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = self._generate_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_code():
        return uuid.uuid4().hex[:8].upper()


class ReferralClick(models.Model):
    """Track each click on an affiliate link."""
    affiliate = models.ForeignKey(Affiliate, on_delete=models.CASCADE, related_name='clicks')
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    session_id = models.CharField(max_length=100, blank=True)
    referrer_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Referral(models.Model):
    """A successful referral that led to a sale."""
    affiliate = models.ForeignKey(Affiliate, on_delete=models.CASCADE, related_name='referrals')
    referred_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='affiliate_referrals')
    commission_earned = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    commission_rate_used = models.DecimalField(max_digits=5, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    paid = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.affiliate.user.username} — Order #{self.order.id} — {self.commission_earned}'


# ---------------------------------------------------------------------------
# Business Logic
# ---------------------------------------------------------------------------
def get_or_create_affiliate(user):
    """Get or create an affiliate profile for a user."""
    aff, _ = Affiliate.objects.get_or_create(user=user)
    return aff


def calculate_commission(order, rate=None):
    """
    Calculate commission for an order.
    Uses the affiliate's rate or the default 10%.
    Commission is calculated on the order subtotal (not including shipping/tax).
    """
    if rate is None:
        rate = Decimal('0.10')
    return _money(order.subtotal * rate)


def record_referral_sale(affiliate, order):
    """
    Record a commission for a referred order.
    Called when an order is placed by a referred customer.
    """
    rate = affiliate.commission_rate
    commission = calculate_commission(order, rate)

    referral = Referral.objects.create(
        affiliate=affiliate,
        order=order,
        commission_earned=commission,
        commission_rate_used=rate,
    )

    affiliate.total_earned += commission
    affiliate.save(update_fields=['total_earned'])

    logger.info(
        'Affiliate %s earned %.2f on Order #%d',
        affiliate.user.username, commission, order.id
    )
    return referral


def get_referral_code_from_session(request):
    """Extract referral code from session (set when user clicks affiliate link)."""
    return request.session.get('affiliate_ref_code')


def set_referral_code_in_session(request, code):
    """Store referral code in session when user clicks an affiliate link."""
    request.session['affiliate_ref_code'] = code


def apply_referral_to_user(user, code):
    """
    Link a newly registered user to an affiliate via referral code.
    Should be called after user creation.
    """
    if not code:
        return None
    try:
        affiliate = Affiliate.objects.get(referral_code=code, is_active=True)
        # Store the relationship — we'll link orders later
        Referral.objects.create(
            affiliate=affiliate,
            referred_user=user,
            order=None,
            commission_earned=Decimal('0.00'),
            commission_rate_used=affiliate.commission_rate,
        )
        return affiliate
    except Affiliate.DoesNotExist:
        logger.warning('Invalid referral code used: %s', code)
        return None