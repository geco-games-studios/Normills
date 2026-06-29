from django.contrib import admin
from django.utils import timezone
from .models import Category, Product, ProductVariant, ProductImage, ProductSubcategory, CashierContact, PaymentInfo, NewsletterSubscriber, SocialLink, StorefrontControl, Cart, CartItem, Order, OrderItem, Brand, BotConversation, LearnedKeyword, StockAdjustment, MerchantPayout
from .payment import best_lenco_data, get_collection_status, lenco_data_items


FINAL_LENCO_STATUSES = ('successful', 'failed')


def _order_payment_status(lenco_status):
    if lenco_status == 'successful':
        return 'completed'
    if lenco_status in ('pay-offline', 'pending', '3ds-auth-required'):
        return 'processing'
    return 'failed'


def _lenco_data_from_response(response):
    if not response:
        return {}
    return best_lenco_data(response)


def _stored_lenco_responses(order):
    details = order.payment_details or {}
    for key in ('lenco_status_refresh', 'lenco_response', 'otp_response'):
        response = details.get(key)
        if response:
            yield response


def _stored_lenco_references(order):
    references = []
    if order.payment_reference:
        references.append(order.payment_reference)

    for response in _stored_lenco_responses(order):
        for data in lenco_data_items(response):
            for key in ('lencoReference', 'reference', 'id'):
                value = data.get(key)
                if value and value not in references:
                    references.append(value)

    return references


def _best_stored_lenco_response(order):
    fallback = None
    for response in _stored_lenco_responses(order):
        data = _lenco_data_from_response(response)
        if data.get('status') in FINAL_LENCO_STATUSES:
            return response
        fallback = fallback or response
    return fallback


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'new_in_message']
    list_editable = ['new_in_message']
    prepopulated_fields = {'slug': ('name',)}

@admin.register(ProductSubcategory)
class ProductSubcategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'created_at']
    prepopulated_fields = {'slug': ('name',)}

@admin.register(CashierContact)
class CashierContactAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'phone', 'active', 'updated_at']
    list_editable = ['active']
    search_fields = ['name', 'email', 'phone']

@admin.register(PaymentInfo)
class PaymentInfoAdmin(admin.ModelAdmin):
    list_display = ['title', 'number', 'recipient_name', 'active', 'sort_order', 'updated_at']
    list_editable = ['number', 'recipient_name', 'active', 'sort_order']
    search_fields = ['title', 'number', 'recipient_name']

@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ['email', 'active', 'created_at']
    list_filter = ['active', 'created_at']
    list_editable = ['active']
    search_fields = ['email']

@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display = ['label', 'url', 'active', 'sort_order', 'updated_at']
    list_editable = ['url', 'active', 'sort_order']
    search_fields = ['label', 'url']

@admin.register(StorefrontControl)
class StorefrontControlAdmin(admin.ModelAdmin):
    list_display = ['header_mode', 'new_in_message', 'updated_at']

class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'subcategory', 'brand', 'price', 'stock', 'offline_stock', 'low_stock_threshold', 'available', 'show_selling_fast', 'created', 'updated']
    list_filter = ['available', 'show_selling_fast', 'created', 'updated', 'category', 'brand']
    list_editable = ['subcategory', 'price', 'stock', 'offline_stock', 'low_stock_threshold', 'available', 'show_selling_fast']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductVariantInline, ProductImageInline]

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
        'order_status',
        'payment_method',
        'admin_payment_status',
        'payment_confirmed',
        'delivery_method',
        'lenco_status',
        'payment_reference',
        'created',
        'total',
    ]
    list_filter = ['status', 'payment_method', 'payment_status', 'payment_confirmed', 'delivery_method', 'created']
    search_fields = ['id', 'email', 'phone', 'payment_reference', 'transaction_id']
    readonly_fields = ['created', 'updated', 'payment_reference', 'payment_details', 'stock_deducted_at']
    actions = ['refresh_lenco_payment_status']
    inlines = [OrderItemInline]

    @admin.display(description='Order Status', ordering='status')
    def order_status(self, obj):
        return obj.get_status_display()

    @admin.display(description='Payment Status', ordering='payment_status')
    def admin_payment_status(self, obj):
        if obj.payment_status == 'completed':
            return 'Paid'
        return obj.get_payment_status_display()

    @admin.display(description='Lenco Status')
    def lenco_status(self, obj):
        data = _lenco_data_from_response(_best_stored_lenco_response(obj))
        return data.get('status') or '-'

    @admin.action(description='Refresh selected orders from Lenco')
    def refresh_lenco_payment_status(self, request, queryset):
        updated = 0
        failed = 0

        for order in queryset:
            references = _stored_lenco_references(order)
            if not references:
                failed += 1
                continue

            response = _best_stored_lenco_response(order)
            for reference in references:
                fresh_response = get_collection_status(reference)
                fresh_status = _lenco_data_from_response(fresh_response).get('status')
                if fresh_response.get('status') and fresh_status in FINAL_LENCO_STATUSES:
                    response = fresh_response
                    break
                if not response and fresh_response.get('status'):
                    response = fresh_response

            if not response or not response.get('status'):
                failed += 1
                order.payment_details = {
                    **(order.payment_details or {}),
                    'lenco_status_refresh': response,
                }
                order.save(update_fields=['payment_details'])
                continue

            payment_data = response.get('data') or {}
            lenco_status = payment_data.get('status', 'pending')
            order.payment_status = _order_payment_status(lenco_status)
            if order.payment_status == 'completed':
                order.status = 'paid'
                order.payment_confirmed = True
            order.payment_details = {
                **(order.payment_details or {}),
                'lenco_status_refresh': response,
            }
            order.save(update_fields=['payment_status', 'status', 'payment_confirmed', 'payment_details'])
            updated += 1

        self.message_user(
            request,
            f'Refreshed {updated} order(s) from Lenco. {failed} order(s) could not be refreshed.'
        )


@admin.register(MerchantPayout)
class MerchantPayoutAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'store',
        'order_number',
        'product_name',
        'amount',
        'status',
        'paid_at',
        'created_at',
    ]
    list_filter = ['status', 'store', 'created_at', 'paid_at']
    search_fields = ['store__name', 'order_item__product__name', 'order_item__order__id']
    readonly_fields = ['store', 'order_item', 'amount', 'created_at', 'updated_at']
    actions = ['refresh_status_from_orders', 'mark_as_paid', 'hold_for_review']

    @admin.display(description='Order', ordering='order_item__order__id')
    def order_number(self, obj):
        return f"#{obj.order_item.order_id}"

    @admin.display(description='Product', ordering='order_item__product__name')
    def product_name(self, obj):
        return obj.order_item.product.name

    @admin.action(description='Refresh payout status from order fulfillment')
    def refresh_status_from_orders(self, request, queryset):
        for payout in queryset.select_related('order_item__order', 'order_item__product__store'):
            payout.refresh_from_order()
        self.message_user(request, f'Refreshed {queryset.count()} payout record(s).')

    @admin.action(description='Mark selected payouts as paid')
    def mark_as_paid(self, request, queryset):
        updated = queryset.filter(status__in=['ready', 'held']).update(status='paid', paid_at=timezone.now())
        self.message_user(request, f'Marked {updated} payout record(s) as paid.')

    @admin.action(description='Hold selected payouts for review')
    def hold_for_review(self, request, queryset):
        updated = queryset.exclude(status='paid').update(status='held', paid_at=None)
        self.message_user(request, f'Held {updated} payout record(s) for review.')


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = [
        'created_at',
        'product',
        'previous_online_stock',
        'new_online_stock',
        'previous_offline_stock',
        'new_offline_stock',
        'user',
        'reason',
    ]
    list_filter = ['created_at', 'product']
    search_fields = ['product__name', 'reason', 'user__username']
    readonly_fields = [
        'created_at',
        'product',
        'user',
        'previous_online_stock',
        'new_online_stock',
        'previous_offline_stock',
        'new_offline_stock',
        'reason',
    ]
