from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from manager.models import Store
from users.models import User

class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    
    class Meta:
        verbose_name_plural = 'Categories'
    
    def __str__(self):
        return self.name
    
class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='products')  # Link to Store
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
    store = models.ForeignKey('Store', on_delete=models.CASCADE, null=True, blank=True)
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
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='mobile_money')
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
            send_sms(recipient_phone, message)
        except Exception as e:
            print(f"Failed to send SMS: {e}")
            
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
            self.send_sms_notification(store_owner_message, self.store.owner.phone_number)

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
            self.send_sms_notification(store_owner_message, self.store.owner.phone_number)

    def notify_payment_confirmed(self):
        """
        Notify the user and store owner that the payment has been confirmed.
        """
        if not self.payment_confirmed:
            self.payment_confirmed = True
            self.save()

            # Prepare receipt message
            receipt_message = (
                f"Receipt for Transaction ID: {self.transaction_id}\n"
                f"Product Details: {self.product_details()}\n"
                f"Price: {self.total}\n"
                f"Delivered At: {self.delivered_at}\n"
                f"Store Owner: {self.store.owner.username}\n"
                f"Thank you for your purchase!"
            )

            # Send SMS to user and store owner
            self.send_sms_notification(receipt_message, self.phone)
            self.send_sms_notification(receipt_message, self.store.owner.phone_number)

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

class Store(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stores')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def total_revenue(self):
        return sum(order.total for order in self.orders.all())