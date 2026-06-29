import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote

from django.conf import settings
from django.db import models
from django.utils import timezone
from manager.models import Store
from users.models import User
from .sms_client import SMSClient

logger = logging.getLogger(__name__)
MONEY_PLACES = Decimal('0.01')

class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    new_in_message = models.CharField(max_length=240, blank=True)
    
    class Meta:
        verbose_name_plural = 'Categories'
    

    def __str__(self):
        return self.name


# Move Brand to top-level
class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name



# Move Product to top-level
class Product(models.Model):
    PUBLICATION_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
    ]

    SEASON_CHOICES = [
        ('spring', 'Spring'),
        ('summer', 'Summer'),
        ('fall', 'Fall'),
        ('winter', 'Winter'),
        ('all_seasons', 'All Seasons'),
    ]

    FABRIC_CHOICES = [
        ('cotton', 'Cotton'),
        ('silk', 'Silk'),
        ('linen', 'Linen'),
        ('wool', 'Wool'),
        ('leather', 'Leather'),
    ]

    COLOR_CHOICES = [
        ('red', 'Red'),
        ('blue', 'Blue'),
        ('green', 'Green'),
        ('black', 'Black'),
        ('white', 'White'),
        ('yellow', 'Yellow'),
    ]

    COST_RANGE_CHOICES = [
        ('budget', 'Budget'),
        ('value', 'Value'),
        ('standard', 'Standard'),
        ('premium', 'Premium'),
        ('luxury', 'Luxury'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='products')  # Link to Store
    brand = models.ForeignKey('Brand', on_delete=models.CASCADE, related_name='products', null=True, blank=True)
    description = models.TextField(blank=True)
    subcategory = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='products/')
    stock = models.PositiveIntegerField(default=1)
    offline_stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    publication_status = models.CharField(max_length=20, choices=PUBLICATION_STATUS_CHOICES, default='published')
    available = models.BooleanField(default=True)
    show_selling_fast = models.BooleanField(default=False)
    season = models.CharField(max_length=20, choices=SEASON_CHOICES, blank=True, null=True)
    fabric = models.CharField(max_length=20, choices=FABRIC_CHOICES, blank=True, null=True)
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, blank=True, null=True)
    cost_range = models.CharField(max_length=20, choices=COST_RANGE_CHOICES, blank=True, null=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return self.name

    @property
    def total_stock(self):
        return self.stock + self.offline_stock

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold

    @property
    def is_published(self):
        return self.publication_status == 'published'


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='supporting_images')
    image = models.ImageField(upload_to='products/supporting/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.product.name} image"


class ProductSubcategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Product Subcategory'
        verbose_name_plural = 'Product Subcategories'

    def __str__(self):
        return self.name


class CashierContact(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PaymentInfo(models.Model):
    title = models.CharField(max_length=120)
    number = models.CharField(max_length=40)
    recipient_name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'title']
        verbose_name = 'Payment Info'
        verbose_name_plural = 'Payment Info'

    def __str__(self):
        return f"{self.title} - {self.number}"


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.email


class SocialLink(models.Model):
    label = models.CharField(max_length=60, unique=True)
    url = models.URLField(blank=True)
    active = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'label']

    def __str__(self):
        return self.label


class StorefrontControl(models.Model):
    HEADER_MODE_CHOICES = [
        ('interactive', 'Interactive menu'),
        ('banner', 'Single banner'),
    ]

    header_mode = models.CharField(max_length=20, choices=HEADER_MODE_CHOICES, default='interactive')
    header_banner = models.ImageField(upload_to='storefront/banners/', blank=True)
    today_new_in_message = models.CharField(
        max_length=240,
        default="Fresh styles, latest arrivals, and new products added to the storefront.",
    )
    new_in_message = models.CharField(
        max_length=240,
        default='Fresh styles, latest arrivals, and new products added to the storefront.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Storefront Control'
        verbose_name_plural = 'Storefront Controls'

    def __str__(self):
        return 'Storefront controls'


class LearnedKeyword(models.Model):
    term = models.CharField(max_length=100, unique=True)
    normalized_term = models.CharField(max_length=100, unique=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='learned_keywords')
    brand = models.ForeignKey('Brand', on_delete=models.SET_NULL, null=True, blank=True, related_name='learned_keywords')
    product = models.ForeignKey('Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='learned_keywords')
    usage_count = models.PositiveIntegerField(default=1)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen']
        verbose_name = 'Learned Keyword'
        verbose_name_plural = 'Learned Keywords'

    def __str__(self):
        return self.term

class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    color = models.CharField(max_length=50, blank=True)
    size = models.CharField(max_length=50, blank=True)
    price_adjustment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    def __str__(self):
        variant_info = []
        if self.color:
            variant_info.append(self.color)
        if self.size:
            variant_info.append(self.size)
        return f"{self.product.name} - {' / '.join(variant_info)}"

class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    session_id = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Cart {self.id}"
    
    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())
    
    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    
    def __str__(self):
        return f"{self.quantity} x {self.product.name}"
    
    @property
    def subtotal(self):
        base_price = self.product.price
        if self.variant:
            base_price += self.variant.price_adjustment
        return base_price * self.quantity
    
class Order(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('payment_awaiting', 'Payment awaiting confirmation'),
        ('paid', 'Paid'),
        ('packing', 'Packing'),
        ('dispatched', 'Dispatched'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('cleared', 'Cleared from cashier'),
        ('refunded', 'Refunded'),
    )

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    )

    PAYMENT_METHOD_CHOICES = (
        ('mobile_money', 'Mobile Money'),
        ('card', 'Credit/Debit Card'),
        ('cash', 'Pay on delivery/pickup'),
    )

    DELIVERY_METHOD_CHOICES = (
        ('delivery', 'Delivery'),
        ('pickup', 'Pickup'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    address = models.CharField(max_length=250)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    phone = models.CharField(max_length=20)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_method = models.CharField(max_length=20, choices=DELIVERY_METHOD_CHOICES, default='delivery')
    notes = models.TextField(blank=True)
    

    # Payment fields
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    payment_details = models.JSONField(blank=True, null=True)
    
    # Delivery Fields
    delivered_at = models.DateTimeField(null=True, blank=True)  # Timestamp when the order is delivered
    payment_confirmed = models.BooleanField(default=False)  # Whether payment is confirmed
    transaction_id = models.CharField(max_length=100, unique=True, blank=True, null=True)  # Unique transaction ID
    stock_deducted_at = models.DateTimeField(null=True, blank=True)
    dispatch_reference = models.CharField(max_length=120, blank=True)
    fulfillment_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created']

    # def __str__(self):
    #     return f'Order {self.id}'
    
    def __str__(self):
        return f'Order {self.id} - {self.transaction_id}'
    
    def send_sms_notification(self, message, recipient_phone):
        """
        Utility method to send an SMS notification.
        """
        try:
            sms_client = SMSClient()
            sms_client.send_sms(recipient_phone, message)
        except Exception as e:
            logger.exception('Failed to send SMS to %s', recipient_phone)

    def get_store_owner_phone_numbers(self):
        store = self.store
        if not store and self.items.exists():
            store = self.items.first().product.store

        owner = getattr(store, 'owner', None)
        if not owner:
            return []

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

        # Deduplicate while preserving order
        seen = set()
        return [num for num in numbers if num and not (num in seen or seen.add(num))]

    def _notify_store_owner(self, message):
        numbers = self.get_store_owner_phone_numbers()
        if not numbers:
            logger.warning('Order %s store owner has no phone numbers configured', self.id)
            return

        for recipient in numbers:
            self.send_sms_notification(message, recipient)

    def notify_shipped(self):
        """
        Notify the user and store owner that the order has been shipped.
        """
        if self.status != 'dispatched':
            self.status = 'dispatched'
            self.save()

            # Prepare messages
            user_message = (
                f"Your order with transaction ID {self.transaction_id} has been shipped. "
                f"Product: {self.product_details()}, Price: {self.total}"
            )
            store_owner_message = (
                f"Order with transaction ID {self.transaction_id} has been shipped. "
                f"Product: {self.product_details()}, Price: {self.total}"
            )

            # Send SMS to user and store owner
            self.send_sms_notification(user_message, self.phone)
            self._notify_store_owner(store_owner_message)

    def notify_delivered(self):
        """
        Notify the user and store owner that the order has been delivered.
        """
        if self.status != 'delivered':
            self.status = 'delivered'
            self.delivered_at = timezone.now()
            self.save()

            # Prepare messages
            user_message = (
                f"Your order with transaction ID {self.transaction_id} has been delivered. "
                f"Product: {self.product_details()}, Price: {self.total}"
            )
            store_owner_message = (
                f"Order with transaction ID {self.transaction_id} has been delivered. "
                f"Product: {self.product_details()}, Price: {self.total}"
            )

            # Send SMS to user and store owner
            self.send_sms_notification(user_message, self.phone)
            self._notify_store_owner(store_owner_message)

    def notify_payment_confirmed(self):
        """
        Notify the user and store owner that the payment has been confirmed.
        """
        if not self.payment_confirmed:
            self.payment_confirmed = True
            self.save()

            # Prepare receipt message
            store_owner = None
            if self.store and getattr(self.store, 'owner', None):
                store_owner = self.store.owner
            elif self.items.exists() and getattr(self.items.first().product.store, 'owner', None):
                store_owner = self.items.first().product.store.owner

            store_owner_user = getattr(store_owner, 'user', None)
            store_owner_name = (
                getattr(store_owner_user, 'username', None)
                or getattr(store_owner, 'store_name', None)
                or 'Store Owner'
            )

            receipt_message = (
                f"Receipt for Transaction ID: {self.transaction_id}\n"
                f"Product Details: {self.product_details()}\n"
                f"Price: {self.total}\n"
                f"Delivered At: {self.delivered_at}\n"
                f"Store Owner: {store_owner_name}\n"
                f"Thank you for your purchase!"
            )

            # Send SMS to user and store owner
            self.send_sms_notification(receipt_message, self.phone)
            self._notify_store_owner(receipt_message)

    def product_details(self):
        """
        Returns a string with details of all products in the order.
        """
        return ", ".join([f"{item.product.name} (x{item.quantity})" for item in self.items.all()])

    @property
    def whatsapp_phone(self):
        digits = ''.join(ch for ch in (self.phone or '') if ch.isdigit())
        if digits.startswith('00'):
            digits = digits[2:]
        if digits.startswith('0') and len(digits) == 10:
            digits = '260' + digits[1:]
        elif len(digits) == 9:
            digits = '260' + digits
        return digits

    @property
    def whatsapp_message(self):
        return (
            f"Hello {self.first_name}, this is Normils Boutique about Order #{self.id}. "
            f"Status: {self.get_status_display()}. "
            f"Items: {self.product_details()}. "
            f"Total: K{self.total}. "
            "Please reply here if you have any delivery questions."
        )

    @property
    def whatsapp_url(self):
        if not self.whatsapp_phone:
            return ''
        return f"https://wa.me/{self.whatsapp_phone}?text={quote(self.whatsapp_message)}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant_info = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    
    def __str__(self):
        return f"{self.quantity} x {self.product.name}"
    
    @property
    def subtotal(self):
        return self.price * self.quantity


class MerchantPayout(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending fulfillment'),
        ('ready', 'Ready for payout'),
        ('paid', 'Paid out'),
        ('held', 'Held for review'),
        ('blocked', 'Blocked'),
    )

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='merchant_payouts')
    order_item = models.OneToOneField(OrderItem, on_delete=models.CASCADE, related_name='merchant_payout')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fee_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    note = models.TextField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.store.name} payout for order #{self.order_item.order_id}"

    def calculated_status(self):
        order = self.order_item.order
        if order.payment_status != 'completed' or order.status in ('cancelled', 'refunded'):
            return 'blocked'
        if self.status in ('paid', 'held'):
            return self.status
        if order.status in ('delivered', 'cleared'):
            return 'ready'
        return 'pending'

    def refresh_from_order(self, save=True):
        self.store = self.order_item.product.store
        self.amount = self.order_item.subtotal
        self.fee_rate = Decimal(str(getattr(settings, 'MERCHANT_PAYOUT_FEE_RATE', '0.00')))
        self.platform_fee = (self.amount * self.fee_rate).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
        self.net_amount = self.amount - self.platform_fee
        self.status = self.calculated_status()
        if self.status != 'paid':
            self.paid_at = None
        if save:
            self.save(update_fields=[
                'store',
                'amount',
                'platform_fee',
                'net_amount',
                'fee_rate',
                'status',
                'paid_at',
                'updated_at',
            ])


class StockAdjustment(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_adjustments')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    previous_online_stock = models.PositiveIntegerField(default=0)
    new_online_stock = models.PositiveIntegerField(default=0)
    previous_offline_stock = models.PositiveIntegerField(default=0)
    new_offline_stock = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product.name}: {self.previous_online_stock} -> {self.new_online_stock}"


class DashboardAnalyticReset(models.Model):
    key = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=100)
    baseline_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reset_at = models.DateTimeField(auto_now=True)
    reset_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f"{self.label} reset at {self.reset_at.isoformat()}"


class OutboundSMSLog(models.Model):
    recipient = models.CharField(max_length=50)
    message = models.TextField()
    payload = models.JSONField(blank=True, null=True)
    response = models.JSONField(blank=True, null=True)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Outbound SMS Log'
        verbose_name_plural = 'Outbound SMS Logs'

    def __str__(self):
        return f"SMS {self.status} to {self.recipient} at {self.created_at.isoformat()}"


class BotConversation(models.Model):
    user = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='bot_conversations')
    session_id = models.CharField(max_length=100, null=True, blank=True)
    product = models.ForeignKey('store.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='bot_conversations')
    message = models.TextField()
    response = models.TextField()
    category_ids = models.JSONField(blank=True, null=True)
    brand_ids = models.JSONField(blank=True, null=True)
    season = models.CharField(max_length=20, blank=True, null=True)
    fabric = models.CharField(max_length=20, blank=True, null=True)
    color = models.CharField(max_length=20, blank=True, null=True)
    cost_range = models.CharField(max_length=20, blank=True, null=True)
    message_tokens = models.PositiveIntegerField(default=0)
    response_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Bot Conversation'
        verbose_name_plural = 'Bot Conversations'

    def __str__(self):
        user_label = self.user.username if self.user else self.session_id or 'Anonymous'
        return f"Bot conversation for {user_label} at {self.created_at.isoformat()}"


class WishlistItem(models.Model):
    """Stores wishlist items for authenticated users or session-based for anonymous users.
    If `user` is null, `session_id` identifies the anonymous owner.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='wishlist_items')
    session_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['session_id']),]

    def __str__(self):
        owner = self.user.username if self.user else (self.session_id or 'Anonymous')
        return f"WishlistItem {self.product.name} for {owner}"
