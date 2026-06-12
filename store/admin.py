from django.contrib import admin
from .models import Category, Product, ProductVariant, Cart, CartItem, Order, OrderItem, Brand, BotConversation, LearnedKeyword
@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}

class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'brand', 'price', 'stock', 'available', 'created', 'updated']
    list_filter = ['available', 'created', 'updated', 'category', 'brand']
    list_editable = ['price', 'stock', 'available']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductVariantInline]

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'session_id', 'created_at', 'updated_at', 'item_count', 'total']
    inlines = [CartItemInline]

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

@admin.register(BotConversation)
class BotConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'session_id', 'product', 'created_at', 'message_tokens', 'response_tokens', 'total_tokens']
    list_filter = ['created_at', 'product']
    search_fields = ['message', 'response', 'session_id']
    readonly_fields = ['created_at']

@admin.register(LearnedKeyword)
class LearnedKeywordAdmin(admin.ModelAdmin):
    list_display = ['term', 'category', 'brand', 'product', 'usage_count', 'last_seen']
    search_fields = ['term', 'normalized_term']
    list_filter = ['category', 'brand']

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'user',
        'first_name',
        'last_name',
        'email',
        'status',
        'payment_method',
        'payment_status',
        'payment_reference',
        'created',
        'total',
    ]
    list_filter = ['status', 'payment_method', 'payment_status', 'created']
    search_fields = ['id', 'email', 'phone', 'payment_reference', 'transaction_id']
    readonly_fields = ['created', 'updated', 'payment_reference', 'payment_details']
    inlines = [OrderItemInline]
