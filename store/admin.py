from django.contrib import admin
from .models import Category, Product, ProductVariant, Cart, CartItem, Order, OrderItem, Brand, BotConversation, LearnedKeyword
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
    actions = ['refresh_lenco_payment_status']
    inlines = [OrderItemInline]

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
                order.status = 'processing'
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
