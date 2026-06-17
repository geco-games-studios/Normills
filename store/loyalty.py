"""
Loyalty Stars Rewards System
-------------------------------
Customers earn Stars on every purchase.
Stars can be redeemed for discounts on future orders.

Earning rate: 1 Star = K10 spent (configurable).
Redeeming: 10 Stars = K5 discount (configurable).
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone
from django.conf import settings

from store.models import Order
from users.models import User

logger = logging.getLogger(__name__)

MONEY_PLACES = Decimal('0.01')


def _money(value):
    return Decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Configuration  (can be overridden in settings.py)
# ---------------------------------------------------------------------------
def _kwacha_per_star():
    """How many Kwacha spent = 1 Star earned."""
    return Decimal(str(getattr(settings, 'KWACHA_PER_STAR', '10')))


def _stars_per_discount_klass():
    """How many Stars needed for the base discount."""
    return int(getattr(settings, 'STARS_PER_DISCOUNT', '10'))


def _discount_value():
    """Discount amount (in Kwacha) per redemption unit."""
    return _money(str(getattr(settings, 'DISCOUNT_VALUE_PER_REDEMPTION', '5')))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class LoyaltyAccount(models.Model):
    """Each user has one loyalty account tracking Stars."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='loyalty')
    total_stars_earned = models.PositiveIntegerField(default=0)
    total_stars_redeemed = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Loyalty Accounts'

    def __str__(self):
        return f'{self.user.username} — {self.balance} Stars'

    @property
    def balance(self):
        """Stars available to redeem."""
        return self.total_stars_earned - self.total_stars_redeemed


class StarTransaction(models.Model):
    """Audit log for every star earned or spent."""

    TRANSACTION_TYPES = (
        ('earned', 'Earned from purchase'),
        ('redeemed', 'Redeemed for discount'),
        ('adjusted', 'Manual adjustment'),
    )

    account = models.ForeignKey(
        LoyaltyAccount, on_delete=models.CASCADE, related_name='transactions'
    )
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='star_transactions'
    )
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    stars = models.IntegerField(help_text='Positive = earned, negative = spent')
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.stars > 0 else ''
        return f'{sign}{self.stars} Stars — {self.transaction_type} — {self.created_at.date()}'


# ---------------------------------------------------------------------------
# Business Logic
# ---------------------------------------------------------------------------
def get_or_create_loyalty(user):
    """Get or create a loyalty account for a user."""
    account, _ = LoyaltyAccount.objects.get_or_create(user=user)
    return account


def calculate_stars_earned(order_total):
    """
    Calculate how many Stars to award based on order total.
    Default: 1 Star per K10 spent, rounded down.
    """
    rate = _kwacha_per_star()
    if rate <= 0:
        return 0
    return int(Decimal(str(order_total)) / rate)


def award_stars(user, order):
    """
    Award Stars to a user for a completed order.
    Should be called when payment is confirmed.
    """
    stars = calculate_stars_earned(order.subtotal)
    if stars <= 0:
        return None

    account = get_or_create_loyalty(user)
    account.total_stars_earned += stars
    account.save(update_fields=['total_stars_earned'])

    transaction = StarTransaction.objects.create(
        account=account,
        order=order,
        transaction_type='earned',
        stars=stars,
        description=f'Earned {stars} Stars from Order #{order.id}',
    )

    logger.info('User %s earned %d Stars from Order #%d', user.username, stars, order.id)
    return transaction


def redeem_stars(user, stars_to_redeem):
    """
    Redeem Stars for a discount.
    Returns the discount amount in Kwacha, or 0 if not enough Stars.
    """
    account = get_or_create_loyalty(user)
    if account.balance < stars_to_redeem:
        logger.warning(
            'User %s tried to redeem %d Stars but only has %d',
            user.username, stars_to_redeem, account.balance
        )
        return Decimal('0.00')

    # Calculate discount: e.g. 10 Stars = K5 discount
    klass_stars = _stars_per_discount_klass()
    klass_value = _discount_value()
    if klass_stars <= 0:
        return Decimal('0.00')

    units = stars_to_redeem // klass_stars
    actual_stars = units * klass_stars
    discount = _money(units * klass_value)

    if actual_stars <= 0:
        return Decimal('0.00')

    account.total_stars_redeemed += actual_stars
    account.save(update_fields=['total_stars_redeemed'])

    StarTransaction.objects.create(
        account=account,
        transaction_type='redeemed',
        stars=-actual_stars,
        description=f'Redeemed {actual_stars} Stars for K{discount} discount',
    )

    logger.info('User %s redeemed %d Stars for K%s', user.username, actual_stars, discount)
    return discount


def get_star_balance(user):
    """Quick helper to get current Star balance."""
    account = get_or_create_loyalty(user)
    return account.balance


def get_earn_rate_description():
    """Human-readable earning rate, e.g. '1 Star per K10'."""
    return f'1 Star per K{_kwacha_per_star()}'