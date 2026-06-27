from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        MERCHANT = 'merchant', 'Merchant'
        VERIFIED_MERCHANT = 'verified_merchant', 'Verified Merchant'
        DELIVERY_PARTNER = 'delivery_partner', 'Delivery Partner'
        ADMINISTRATOR = 'administrator', 'Administrator'
        FINANCE_ADMINISTRATOR = 'finance_administrator', 'Financial Administrator'
        MODERATOR = 'moderator', 'Moderator'
        SUPPORT_OFFICER = 'support_officer', 'Support Officer'

    class VerificationStatus(models.TextChoices):
        UNVERIFIED = 'unverified', 'Unverified'
        PENDING = 'pending', 'Pending Review'
        VERIFIED = 'verified', 'Verified'
        REJECTED = 'rejected', 'Rejected'

    class TrustBadge(models.TextChoices):
        VERIFIED_CUSTOMER = 'verified_customer', 'Verified Customer'
        VERIFIED_MERCHANT = 'verified_merchant', 'Verified Merchant'
        PREMIUM_MERCHANT = 'premium_merchant', 'Premium Merchant'
        TOP_SELLER = 'top_seller', 'Top Seller'
        FAST_DELIVERY = 'fast_delivery', 'Fast Delivery'
        PAYGO_ELIGIBLE = 'paygo_eligible', 'PayGo Eligible'
        TRUSTED_BUSINESS = 'trusted_business', 'Trusted Business'

    role = models.CharField(max_length=32, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
        db_index=True,
    )
    trust_badges = models.JSONField(default=list, blank=True)

    # Legacy flags kept for existing views/forms during the Phase 2 transition.
    is_store_owner = models.BooleanField(default=False)
    is_client = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)

    # Add unique related_name to avoid clashes
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        related_name='custom_user_set',  # Unique related_name
        related_query_name='user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='custom_user_set',  # Unique related_name
        related_query_name='user',
    )

    def __str__(self):
        return self.username

    @property
    def is_customer_role(self):
        return self.role == self.Role.CUSTOMER or self.is_client

    @property
    def is_merchant_role(self):
        return self.role in {self.Role.MERCHANT, self.Role.VERIFIED_MERCHANT} or self.is_store_owner

    @property
    def is_verified_merchant_role(self):
        return self.role == self.Role.VERIFIED_MERCHANT or self.has_trust_badge(self.TrustBadge.VERIFIED_MERCHANT)

    @property
    def can_access_merchant_centre(self):
        return self.is_staff or self.is_superuser or self.is_merchant_role

    @property
    def can_access_finance_admin(self):
        return self.is_superuser or self.role == self.Role.FINANCE_ADMINISTRATOR

    @property
    def can_access_moderation(self):
        return self.is_superuser or self.role in {self.Role.ADMINISTRATOR, self.Role.MODERATOR, self.Role.SUPPORT_OFFICER}

    def has_trust_badge(self, badge):
        return badge in (self.trust_badges or [])
    
# class User(AbstractUser):
#     is_store_owner = models.BooleanField(default=False)

class StoreOwnerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='store_owner_profile')
    store_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20)
    alt_phone_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.user.username} - Store Owner"
    
    
class ClientProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='client_profile')
    phone_number = models.CharField(max_length=20)
    address = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - Client"


class PhoneOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='phone_otps')
    phone = models.CharField(max_length=20)
    code = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP {self.code} for {self.phone} (used={self.used})"
