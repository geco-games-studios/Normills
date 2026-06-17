from django.contrib import admin
from .models import Category, Brand, Product, ProductVariant, Cart, CartItem, Order, OrderItem, LearnedKeyword, BotConversation, WishlistItem, OutboundSMSLog
from .reviews import Review
from .affiliate import Affiliate, ReferralClick, Referral
from .loyalty import LoyaltyAccount, StarTransaction
from .abandoned_cart import AbandonedCartRecord


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'stock', 'available', 'created']
    list_filter = ['available', 'category', 'brand', 'season', 'fabric', 'color', 'cost_range']
    list_editable = ['price', 'stock', 'available']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['product', 'color', 'size', 'price_adjustment']


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'session_id', 'total', 'item_count', 'created_at']
    readonly_fields = ['total', 'item_count']


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ['cart', 'product', 'variant', 'quantity', 'subtotal']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'store', 'total', 'status', 'payment_status', 'payment_method', 'created']
    list_filter = ['status', 'payment_status', 'payment_method']
    search_fields = ['id', 'user__username', 'transaction_id']


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'product', 'quantity', 'price', 'subtotal']


@admin.register(LearnedKeyword)
class LearnedKeywordAdmin(admin.ModelAdmin):
    list_display = ['term', 'usage_count', 'last_seen']


@admin.register(BotConversation)
class BotConversationAdmin(admin.ModelAdmin):
    list_display = ['user', 'session_id', 'message', 'total_tokens', 'created_at']


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'session_id', 'created_at']


@admin.register(OutboundSMSLog)
class OutboundSMSLogAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'status', 'created_at']


# --- New Review Admin ---
@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'rating', 'verified_purchase', 'created_at']
    list_filter = ['rating', 'verified_purchase']
    search_fields = ['product__name', 'user__username', 'comment']


# --- New Affiliate Admin ---
@admin.register(Affiliate)
class AffiliateAdmin(admin.ModelAdmin):
    list_display = ['user', 'referral_code', 'commission_rate', 'balance', 'total_earned', 'is_active']
    list_filter = ['is_active']


@admin.register(ReferralClick)
class ReferralClickAdmin(admin.ModelAdmin):
    list_display = ['affiliate', 'ip_address', 'created_at']


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ['affiliate', 'referred_user', 'order', 'commission_earned', 'paid', 'created_at']


# --- New Loyalty Admin ---
@admin.register(LoyaltyAccount)
class LoyaltyAccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance', 'total_stars_earned', 'total_stars_redeemed']
    search_fields = ['user__username']


@admin.register(StarTransaction)
class StarTransactionAdmin(admin.ModelAdmin):
    list_display = ['account', 'stars', 'transaction_type', 'order', 'created_at']
    list_filter = ['transaction_type']


# --- New Abandoned Cart Admin ---
@admin.register(AbandonedCartRecord)
class AbandonedCartRecordAdmin(admin.ModelAdmin):
    list_display = ['cart', 'user', 'cart_total', 'item_count', 'recovered', 'first_reminder_sent', 'second_reminder_sent', 'final_reminder_sent', 'created_at']
    list_filter = ['recovered', 'first_reminder_sent', 'second_reminder_sent', 'final_reminder_sent']