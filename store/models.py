import json
import logging

from django.db import models
from django.utils import timezone
from manager.models import Store
from users.models import User
from .sms_client import SMSClient

logger = logging.getLogger(__name__)

class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    
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
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='products')  # Link to Store
    brand = models.ForeignKey('Brand', on_delete=models.CASCADE, related_name='products', null=True, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='products/')
    stock = models.PositiveIntegerField(default=1)
    available = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return self.name
    
    
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
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
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
        ('cash', 'Cash on Delivery'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
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
    

    # Payment fields
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    payment_details = models.JSONField(blank=True, null=True)
    
    # Delivery Fields
    delivered_at = models.DateTimeField(null=True, blank=True)  # Timestamp when the order is delivered
    payment_confirmed = models.BooleanField(default=False)  # Whether payment is confirmed
    transaction_id = models.CharField(max_length=100, unique=True, blank=True, null=True)  # Unique transaction ID

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
        if self.status != 'shipped':
            self.status = 'shipped'
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
            store_owner_name = None
            if self.store and getattr(self.store, 'owner', None):
                store_owner_name = self.store.owner.username
            elif self.items.exists() and getattr(self.items.first().product.store, 'owner', None):
                store_owner_name = self.items.first().product.store.owner.username
            else:
                store_owner_name = 'Store Owner'

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
