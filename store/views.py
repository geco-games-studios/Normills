from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib import messages
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.db import close_old_connections, transaction
from django.db.models import F, Q, Min, Max, Sum
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from decimal import Decimal, ROUND_HALF_UP
import os
import re
import threading
import uuid
import json
from django.conf import settings
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .models import Category, Product, ProductVariant, ProductImage, ProductSubcategory, CashierContact, PaymentInfo, NewsletterSubscriber, SocialLink, StorefrontControl, Cart, CartItem, Order, OrderItem, Brand, BotConversation, LearnedKeyword, WishlistItem, StockAdjustment, DashboardAnalyticReset, MerchantPayout, PayoutBatch, PayGoApplication, DealRequest
from .ml import recommend_products_from_context
from .forms import CustomUserCreationForm, CheckoutForm, DealRequestForm, MerchantDealResponseForm, MerchantProductForm, PayGoApplicationForm, prepare_product_image
from store.sms_client import SMSClient
from django.utils import timezone
from datetime import timedelta
from .payment import best_lenco_data, get_collection_status, lenco_data_items, process_lenco_payment, submit_lenco_otp
from .sms_service import send_order_sms, send_order_receipt_sms
from .whatsapp_service import send_admin_whatsapp_order_receipt
from manager.models import Store
from users.models import ClientProfile
from users.permissions import delivery_partner_required, finance_admin_required, merchant_required, platform_admin_required
from users.phone_verification import normalize_phone as normalize_account_phone, send_phone_verification_code

import logging
import csv

logger = logging.getLogger(__name__)

MONEY_PLACES = Decimal('0.01')
MAX_SUPPORTING_PRODUCT_IMAGES = 6


def _money(value):
    return Decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _checkout_amounts(subtotal, payment_method='cash'):
    subtotal = _money(subtotal)
    shipping = _money(getattr(settings, 'CHECKOUT_SHIPPING_FEE', '0.00'))
    base_tax = _money(subtotal * Decimal(str(getattr(settings, 'CHECKOUT_TAX_RATE', '0.00'))))
    mobile_money_fee = Decimal('0.00')

    if payment_method == 'mobile_money':
        fee_base = subtotal + shipping + base_tax
        fixed_fee = Decimal(str(getattr(settings, 'LENCO_MOBILE_MONEY_FIXED_FEE', '8.50')))
        percent_fee = Decimal(str(getattr(settings, 'LENCO_MOBILE_MONEY_PERCENT_FEE', '0.01')))
        mobile_money_fee = _money(fixed_fee + (fee_base * percent_fee))

    tax = _money(base_tax + mobile_money_fee)
    total = _money(subtotal + shipping + tax)

    return {
        'subtotal': subtotal,
        'shipping': shipping,
        'base_tax': base_tax,
        'mobile_money_fee': mobile_money_fee,
        'tax': tax,
        'total': total,
    }


def _money_display(value):
    return f"K{_money(value):,.2f}"


def _active_payment_infos():
    return PaymentInfo.objects.filter(active=True).order_by('sort_order', 'title')


def _payment_info_payload():
    return [
        {
            'title': info.title,
            'number': info.number,
            'recipient_name': info.recipient_name,
        }
        for info in _active_payment_infos()
    ]


def _payment_confirmed_receipt_message(order):
    return (
        f"Payment Confirmed. Receipt for Order #{order.id}: {_money_display(order.total)}. "
        "Your order will be delivered in 3 - 4 business days depending on your location via courier service. "
        "For any questions contact us."
    )


def _message_payment_text(order):
    payment_infos = list(_active_payment_infos())
    lines = [
        f"Hello, Thank You for shopping with Normils Online, your Bill due is {_money_display(order.total)}.",
        "Tap Made Payment to receive a secure Lenco payment prompt on your phone for this amount.",
    ]
    if payment_infos:
        lines.append("If the prompt fails, you can still contact the cashier using the payment info below:")
        lines.extend(
            f"{info.title}: {info.number} - {info.recipient_name}"
            for info in payment_infos
        )
    else:
        lines.append("A cashier will share payment details shortly.")
    return "\n".join(lines)


def _order_payment_status(lenco_status):
    if lenco_status == 'successful':
        return 'completed'
    if lenco_status in ('pay-offline', 'pending', '3ds-auth-required'):
        return 'processing'
    return 'failed'


def _order_lenco_references(order):
    references = []
    if order.payment_reference:
        references.append(order.payment_reference)

    details = order.payment_details or {}
    for key in ('lenco_status_refresh', 'lenco_response', 'otp_response'):
        for data in lenco_data_items(details.get(key)):
            for ref_key in ('lencoReference', 'reference', 'id'):
                value = data.get(ref_key)
                if value and value not in references:
                    references.append(value)

    return references


def _get_order_collection_status(order):
    fallback_response = None
    for reference in _order_lenco_references(order):
        response = get_collection_status(reference)
        if not response.get('status'):
            fallback_response = fallback_response or response
            continue

        lenco_status = best_lenco_data(response).get('status')
        if lenco_status in ('successful', 'failed'):
            return response
        fallback_response = response

    return fallback_response or {
        'status': False,
        'message': 'No payment reference found',
        'data': None,
    }


def _get_wishlist_count(request):
    if request.user.is_authenticated:
        return WishlistItem.objects.filter(user=request.user).count()
    session_wishlist = request.session.get('wishlist', [])
    return len(session_wishlist)


def _wants_json(request):
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in request.META.get('HTTP_ACCEPT', '')
    )


def _parse_positive_int(value, default=1, minimum=1):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def _cart_stock_issues(cart):
    issues = []
    for item in cart.items.select_related('product').all():
        if not item.product.available or item.product.stock <= 0:
            issues.append(f"{item.product.name} is out of stock.")
        elif item.quantity > item.product.stock:
            issues.append(
                f"Only {item.product.stock} of {item.product.name} available. "
                f"Your cart has {item.quantity}."
            )
    return issues


def _deduct_stock_for_order(order):
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        if locked_order.stock_deducted_at:
            return locked_order

        items = list(locked_order.items.select_related('product').all())
        product_ids = [item.product_id for item in items]
        products = {
            product.id: product
            for product in Product.objects.select_for_update().filter(id__in=product_ids)
        }

        shortages = []
        for item in items:
            product = products[item.product_id]
            if not product.available or product.stock < item.quantity:
                shortages.append(f"{product.name}: {product.stock} available, {item.quantity} ordered")

        if shortages:
            raise ValueError("Stock shortage: " + "; ".join(shortages))

        for item in items:
            product = products[item.product_id]
            product.stock -= item.quantity
            if product.stock == 0:
                product.available = False
            product.save(update_fields=['stock', 'available', 'updated'])

        locked_order.stock_deducted_at = timezone.now()
        locked_order.save(update_fields=['stock_deducted_at'])
        return locked_order


def _set_order_paid(order):
    was_confirmed = order.payment_confirmed
    order.payment_status = 'completed'
    if order.status in ('pending', 'payment_awaiting'):
        order.status = 'paid'
    order.save(update_fields=['payment_status', 'status'])
    order = _deduct_stock_for_order(order)
    if not was_confirmed:
        order.notify_payment_confirmed()
    return order


def _send_cashier_order_message(order, message):
    try:
        order.send_sms_notification(message, order.phone)
        order._notify_store_owner(message)
    except Exception:
        logger.exception('Cashier order message failed for Order ID %s', order.id)


def _order_cashier_message(order):
    return (
        f"New Normils order #{order.id}\n"
        f"Customer: {order.first_name} {order.last_name}\n"
        f"Phone: {order.phone}\n"
        f"Email: {order.email or 'Not provided'}\n"
        f"Items: {order.product_details()}\n"
        f"Total: K{order.total}"
    )


def _notify_cashiers_order_created(order):
    contacts = CashierContact.objects.filter(active=True)
    if not contacts.exists():
        logger.warning('Order %s has no active cashier contacts configured', order.id)
        return

    message = _order_cashier_message(order)
    sms_client = SMSClient()
    for contact in contacts:
        if contact.phone:
            try:
                sms_client.send_sms(contact.phone, message)
            except Exception:
                logger.exception('Cashier SMS failed for order %s to %s', order.id, contact.phone)
        if contact.email:
            try:
                send_mail(
                    f"New Normils Order #{order.id}",
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [contact.email],
                    fail_silently=False,
                )
            except Exception:
                logger.exception('Cashier email failed for order %s to %s', order.id, contact.email)


def _remember_order_for_session(request, order):
    order_ids = request.session.get('guest_order_ids', [])
    if not isinstance(order_ids, list):
        order_ids = []
    if order.id not in order_ids:
        order_ids.append(order.id)
    request.session['guest_order_ids'] = order_ids[-20:]


def _can_access_order(request, order):
    if request.user.is_authenticated:
        return request.user.is_superuser or order.user_id == request.user.id
    return order.id in request.session.get('guest_order_ids', [])


@csrf_exempt
def add_to_wishlist(request):
    """AJAX endpoint to add a product to wishlist. Accepts POST JSON: {product_id: int}.
    Works for authenticated users (persisted) and anonymous users (session).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        payload = request.POST or {}

    product_id = payload.get('product_id') or request.POST.get('product_id')
    if not product_id:
        return JsonResponse({'success': False, 'error': 'product_id required'}, status=400)

    try:
        product = Product.objects.get(id=int(product_id))
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

    if request.user.is_authenticated:
        obj, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
        count = WishlistItem.objects.filter(user=request.user).count()
        return JsonResponse({'success': True, 'added': created, 'count': count})
    else:
        session_list = request.session.get('wishlist', [])
        pid = str(product.id)
        added = False
        if pid not in session_list:
            session_list.append(pid)
            request.session['wishlist'] = session_list
            added = True
        return JsonResponse({'success': True, 'added': added, 'count': len(session_list)})


@csrf_exempt
def remove_from_wishlist(request):
    """AJAX endpoint to remove a product from wishlist."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        payload = request.POST or {}

    product_id = payload.get('product_id') or request.POST.get('product_id')
    if not product_id:
        return JsonResponse({'success': False, 'error': 'product_id required'}, status=400)

    try:
        product = Product.objects.get(id=int(product_id))
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

    if request.user.is_authenticated:
        deleted, _ = WishlistItem.objects.filter(user=request.user, product=product).delete()
        count = WishlistItem.objects.filter(user=request.user).count()
        return JsonResponse({'success': True, 'removed': deleted > 0, 'count': count})
    else:
        session_list = request.session.get('wishlist', [])
        pid = str(product.id)
        removed = False
        if pid in session_list:
            session_list = [p for p in session_list if p != pid]
            request.session['wishlist'] = session_list
            removed = True
        return JsonResponse({'success': True, 'removed': removed, 'count': len(session_list)})


def wishlist(request):
    if request.user.is_authenticated:
        products = Product.objects.filter(wishlisted_by__user=request.user).distinct()
    else:
        wishlist_ids = request.session.get('wishlist', [])
        valid_ids = []
        for pid in wishlist_ids:
            try:
                valid_ids.append(int(pid))
            except (ValueError, TypeError):
                continue
        products = Product.objects.filter(id__in=valid_ids, available=True)

    return render(request, 'wishlist.html', {
        'products': products,
        'wishlist_ids': [str(p.id) for p in products],
    })


def contact_us(request):
    return render(request, 'contact_us.html')


def shipping_policy(request):
    return render(request, 'shipping_policy.html')


def returns_refunds(request):
    return render(request, 'returns_refunds.html')


def get_or_create_cart(request):
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            return cart
        session_id = request.session.get('cart_id')
        if session_id:
            session_cart = Cart.objects.filter(session_id=session_id).first()
            if session_cart:
                session_cart.user = request.user
                session_cart.session_id = None
                session_cart.save()
                return session_cart
        
        return Cart.objects.create(user=request.user)
    else:
        session_id = request.session.get('cart_id')
        if not session_id:
            session_id = get_random_string(32)
            request.session['cart_id'] = session_id
        
        cart = Cart.objects.filter(session_id=session_id).first()
        if not cart:
            cart = Cart.objects.create(session_id=session_id)
        
        return cart


def _get_user_interest_values(request, current_product=None):
    category_ids = set()
    brand_ids = set()

    if current_product:
        category_ids.add(current_product.category_id)
        if current_product.brand_id:
            brand_ids.add(current_product.brand_id)

    viewed_product_ids = request.session.get('viewed_product_ids', [])
    if not isinstance(viewed_product_ids, list):
        try:
            viewed_product_ids = json.loads(viewed_product_ids)
        except Exception:
            viewed_product_ids = []

    for product_id in viewed_product_ids:
        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            continue
        product = Product.objects.filter(id=product_id).first()
        if product:
            category_ids.add(product.category_id)
            if product.brand_id:
                brand_ids.add(product.brand_id)

    if request.user.is_authenticated:
        order_items = OrderItem.objects.filter(order__user=request.user).select_related('product')
        for item in order_items:
            product = item.product
            category_ids.add(product.category_id)
            if product.brand_id:
                brand_ids.add(product.brand_id)

    return category_ids, brand_ids


def extract_bot_interest(message):
    category_ids = set()
    brand_ids = set()
    season = None
    fabric = None
    color = None
    cost_range = None
    normalized = (message or '').lower()
    if not normalized:
        return category_ids, brand_ids, season, fabric, color, cost_range

    for category in Category.objects.all():
        if category.name.lower() in normalized:
            category_ids.add(category.id)

    for brand in Brand.objects.all():
        if brand.name.lower() in normalized:
            brand_ids.add(brand.id)

    for code, label in Product.SEASON_CHOICES:
        if code in normalized or label.lower() in normalized:
            season = code
            break

    for code, label in Product.FABRIC_CHOICES:
        if code in normalized or label.lower() in normalized:
            fabric = code
            break

    for code, label in Product.COLOR_CHOICES:
        if code in normalized or label.lower() in normalized:
            color = code
            break

    for code, label in Product.COST_RANGE_CHOICES:
        if code in normalized or label.lower() in normalized:
            cost_range = code
            break

    for product in Product.objects.filter(available=True).select_related('category', 'brand'):
        product_name = product.name.lower()
        category_name = product.category.name.lower() if product.category else ''
        brand_name = product.brand.name.lower() if product.brand else ''
        if product_name in normalized or category_name in normalized or (brand_name and brand_name in normalized):
            if product.category_id:
                category_ids.add(product.category_id)
            if product.brand_id:
                brand_ids.add(product.brand_id)
            if product.season and not season:
                season = product.season
            if product.fabric and not fabric:
                fabric = product.fabric
            if product.color and not color:
                color = product.color
            if product.cost_range and not cost_range:
                cost_range = product.cost_range

    return category_ids, brand_ids, season, fabric, color, cost_range


def get_bot_interest_values(request):
    category_ids = set()
    brand_ids = set()
    seasons = set()
    fabrics = set()
    colors = set()
    cost_ranges = set()

    if request.user.is_authenticated:
        conversations = BotConversation.objects.filter(user=request.user).order_by('-created_at')[:50]
    else:
        session_id = request.session.get('bot_session_id')
        if not session_id:
            return category_ids, brand_ids, seasons, fabrics, colors, cost_ranges
        conversations = BotConversation.objects.filter(session_id=session_id).order_by('-created_at')[:50]

    for convo in conversations:
        if convo.category_ids:
            category_ids.update(convo.category_ids)
        if convo.brand_ids:
            brand_ids.update(convo.brand_ids)
        if convo.season:
            seasons.add(convo.season)
        if convo.fabric:
            fabrics.add(convo.fabric)
        if convo.color:
            colors.add(convo.color)
        if convo.cost_range:
            cost_ranges.add(convo.cost_range)

    return category_ids, brand_ids, seasons, fabrics, colors, cost_ranges


def get_personalized_products(request, exclude_product=None, limit=6):
    category_ids, brand_ids = _get_user_interest_values(request, exclude_product)
    bot_category_ids, bot_brand_ids, seasons, fabrics, colors, cost_ranges = get_bot_interest_values(request)
    category_ids.update(bot_category_ids)
    brand_ids.update(bot_brand_ids)

    category_slug = None
    brand_slug = None
    if category_ids:
        category_slug = Category.objects.filter(id__in=category_ids).values_list('slug', flat=True).first()
    if brand_ids:
        brand_slug = Brand.objects.filter(id__in=brand_ids).values_list('slug', flat=True).first()

    ml_recommendations = recommend_products_from_context(
        category=category_slug,
        brand=brand_slug,
        season=next(iter(seasons), None),
        fabric=next(iter(fabrics), None),
        color=next(iter(colors), None),
        cost_range=next(iter(cost_ranges), None),
        exclude_product=exclude_product,
        limit=limit,
    )
    if ml_recommendations:
        return ml_recommendations

    products = Product.objects.filter(available=True)
    if exclude_product:
        products = products.exclude(id=exclude_product.id)

    filters = Q()
    if category_ids:
        filters |= Q(category_id__in=category_ids)
    if brand_ids:
        filters |= Q(brand_id__in=brand_ids)
    if seasons:
        filters |= Q(season__in=seasons)
    if fabrics:
        filters |= Q(fabric__in=fabrics)
    if colors:
        filters |= Q(color__in=colors)
    if cost_ranges:
        filters |= Q(cost_range__in=cost_ranges)

    if filters:
        recommended = products.filter(filters).distinct().order_by('-created')[:limit]
        if recommended.exists():
            return recommended

    return products.order_by('-created')[:limit]


BASE_STOREFRONT_FILTERS = [
    {
        'label': 'Tops',
        'slug': 'tops',
        'terms': ['top', 'tops', 'shirt', 'blouse', 'tee', 't-shirt', 'vest', 'jacket', 'hoodie', 'sweater'],
    },
    {
        'label': 'Bottoms',
        'slug': 'bottoms',
        'terms': ['bottom', 'bottoms', 'trouser', 'pants', 'jeans', 'denim', 'shorts', 'skirt', 'leggings'],
    },
    {
        'label': 'Shoes',
        'slug': 'shoes',
        'terms': ['shoe', 'shoes', 'sneaker', 'sneakers', 'sandal', 'sandals', 'heel', 'heels', 'boot', 'boots'],
    },
    {
        'label': 'Accessories',
        'slug': 'accessories',
        'terms': ['accessory', 'accessories', 'bag', 'belt', 'hat', 'cap', 'jewellery', 'jewelry', 'watch', 'scarf'],
    },
]


def _normalize_filter_slug(value):
    return slugify(value or '').strip('-')


CORE_STOREFRONT_FILTER_SLUGS = {button['slug'] for button in BASE_STOREFRONT_FILTERS}


def _ensure_custom_subcategory(name):
    name = (name or '').strip()
    subcategory_slug = _normalize_filter_slug(name)
    if not name or not subcategory_slug or subcategory_slug in CORE_STOREFRONT_FILTER_SLUGS:
        return None
    subcategory, _ = ProductSubcategory.objects.get_or_create(
        slug=subcategory_slug,
        defaults={'name': name},
    )
    return subcategory


def _storefront_filter_buttons():
    collection_slugs = {'kids-collection', 'mens-collection', 'women-collection'}
    buttons = [dict(button) for button in BASE_STOREFRONT_FILTERS]
    existing_slugs = {button['slug'] for button in buttons}
    for subcategory in ProductSubcategory.objects.order_by('name'):
        if subcategory.slug in existing_slugs:
            continue
        buttons.append({
            'label': subcategory.name,
            'slug': subcategory.slug,
            'subcategory': subcategory.name,
            'terms': [subcategory.name, subcategory.slug.replace('-', ' ')],
        })
        existing_slugs.add(subcategory.slug)
    for category in Category.objects.exclude(slug__in=collection_slugs).order_by('name'):
        if category.slug in existing_slugs:
            continue
        buttons.append({
            'label': category.name,
            'slug': category.slug,
            'category_id': category.id,
            'terms': [category.name, category.slug.replace('-', ' ')],
        })
        existing_slugs.add(category.slug)
    return buttons


def _apply_storefront_filter(products, selected_filter, filter_buttons):
    if not selected_filter:
        return products

    filter_config = next((button for button in filter_buttons if button['slug'] == selected_filter), None)
    if not filter_config:
        return products

    filters = Q()
    filters |= Q(subcategory__iexact=filter_config['label'])
    filters |= Q(subcategory__iexact=filter_config['slug'])
    if filter_config.get('subcategory'):
        filters |= Q(subcategory__iexact=filter_config['subcategory'])

    if filter_config.get('category_id'):
        filters |= Q(category_id=filter_config['category_id'])

    for term in filter_config.get('terms', []):
        filters |= Q(subcategory__icontains=term)
        filters |= Q(name__icontains=term)
        filters |= Q(description__icontains=term)
        filters |= Q(category__name__icontains=term)
        filters |= Q(brand__name__icontains=term)

    return products.filter(filters).distinct()


def home(request):
    categories = Category.objects.all()
    products = Product.objects.filter(available=True, stock__gt=0)
    brands = Brand.objects.all()
    filter_buttons = _storefront_filter_buttons()
    selected_filter = request.GET.get('filter') or ''

    # price bounds for the UI slider
    price_bounds = Product.objects.aggregate(min_price=Min('price'), max_price=Max('price'))
    min_price = price_bounds.get('min_price') or Decimal('0')
    max_price = price_bounds.get('max_price') or Decimal('0')

    # Get filter parameters from the request (support two-handle range)
    price_min = request.GET.get('price_min')
    price_max = request.GET.get('price_max')
    # backward compatibility: single 'price' means max price
    price_filter = request.GET.get('price')
    availability_filter = request.GET.get('availability')
    brand_filters = request.GET.getlist('brand')
    size_filters = request.GET.getlist('size')
    color_filters = request.GET.getlist('color')

    # Apply price filter (min and/or max)
    try:
        if price_min:
            pm = Decimal(price_min)
            products = products.filter(price__gte=pm)
        if price_max:
            pM = Decimal(price_max)
            products = products.filter(price__lte=pM)
        elif price_filter:
            # fallback for single-value param
            pf = Decimal(price_filter)
            products = products.filter(price__lte=pf)
    except Exception:
        # ignore invalid price inputs
        pass

    # Apply availability filter
    if availability_filter:
        if availability_filter == 'in_stock':
            products = products.filter(stock__gt=0)
        elif availability_filter == 'out_of_stock':
            products = products.filter(stock=0)

    # Apply brand filter (supports multiple selections)
    if brand_filters:
        products = products.filter(brand__slug__in=brand_filters)

    # Apply size filter (matches product variants)
    if size_filters:
        products = products.filter(variants__size__in=size_filters).distinct()

    # Apply color filter (product-level or variant-level)
    if color_filters:
        products = products.filter(
            Q(color__in=color_filters) | Q(variants__color__in=color_filters)
        ).distinct()

    products = _apply_storefront_filter(products, selected_filter, filter_buttons)

    personalized_products = []
    recently_viewed_products = []
    viewed_product_ids = request.session.get('viewed_product_ids', [])
    if viewed_product_ids:
        valid_ids = []
        for pid in viewed_product_ids:
            try:
                valid_ids.append(int(pid))
            except (ValueError, TypeError):
                continue
        if valid_ids:
            viewed_products = list(Product.objects.filter(id__in=valid_ids, available=True))
            recently_viewed_products = [p for pid in valid_ids for p in viewed_products if p.id == pid]

    personalized_products = get_personalized_products(request)

    if request.user.is_authenticated:
        wishlist_ids = list(WishlistItem.objects.filter(user=request.user).values_list('product_id', flat=True))
    else:
        wishlist_ids = request.session.get('wishlist', [])

    total_products = Product.objects.filter(available=True, stock__gt=0).count()
    viewed_count = products.count()

    return render(request, 'index.html', {
        'categories': categories,
        'products': products,
        'brands': brands,
        'personalized_products': personalized_products,
        'recently_viewed_products': recently_viewed_products,
        'min_price': min_price,
        'max_price': max_price,
        'selected_min_price': price_min or min_price,
        'selected_max_price': price_max or price_filter or max_price,
        'total_products': total_products,
        'viewed_count': viewed_count,
        'wishlist_ids': [str(product_id) for product_id in wishlist_ids],
        'filter_buttons': filter_buttons,
        'selected_filter': selected_filter,
        'social_links': SocialLink.objects.filter(active=True).exclude(url=''),
    })


def subscribe_newsletter(request):
    if request.method != 'POST':
        return redirect('home')

    email = (request.POST.get('email') or '').strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Enter a valid email address.')
        return redirect(request.META.get('HTTP_REFERER') or 'home')

    subscriber, created = NewsletterSubscriber.objects.get_or_create(
        email=email,
        defaults={'active': True},
    )
    if not created and not subscriber.active:
        subscriber.active = True
        subscriber.save(update_fields=['active'])
    messages.success(request, 'Thanks for subscribing.')
    return redirect(request.META.get('HTTP_REFERER') or 'home')
    
    
def search_products(request):
    query = (request.GET.get('q') or '').strip()
    if query:
        products = Product.objects.filter(available=True, stock__gt=0).filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query) |
            Q(brand__name__icontains=query)
        ).distinct()
    else:
        products = Product.objects.none()
    return render(request, 'search_results.html', {
        'products': products,
        'query': query,
    })

def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    categories = Category.objects.all()
    filter_buttons = _storefront_filter_buttons()
    selected_filter = request.GET.get('filter') or ''
    products = category.products.filter(available=True, stock__gt=0)
    products = _apply_storefront_filter(products, selected_filter, filter_buttons)
    return render(request, 'category_detail.html', {
        'category': category,
        'categories': categories,
        'products': products,
        'filter_buttons': filter_buttons,
        'selected_filter': selected_filter,
    })

def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.prefetch_related('supporting_images'),
        slug=slug,
        available=True,
    )
    variants = product.variants.all()
    supporting_images = product.supporting_images.all()

    viewed_product_ids = request.session.get('viewed_product_ids', [])
    if not isinstance(viewed_product_ids, list):
        try:
            viewed_product_ids = json.loads(viewed_product_ids)
        except Exception:
            viewed_product_ids = []

    if product.id not in viewed_product_ids:
        viewed_product_ids.insert(0, product.id)
    # Keep the session list short for personalization
    viewed_product_ids = viewed_product_ids[:12]
    request.session['viewed_product_ids'] = viewed_product_ids

    recommended_products = get_personalized_products(request, exclude_product=product)
    product_url = request.build_absolute_uri()
    paygo_application = None
    active_deal = None
    if request.user.is_authenticated:
        paygo_application = PayGoApplication.objects.filter(
            customer=request.user,
            product=product,
        ).exclude(status__in=['rejected', 'cancelled', 'completed']).order_by('-created_at').first()
        active_deal = DealRequest.objects.filter(
            customer=request.user,
            product=product,
        ).exclude(status__in=['rejected', 'cancelled', 'converted']).order_by('-updated_at').first()

    return render(request, 'product_details.html', {
        'product': product,
        'variants': variants,
        'supporting_images': supporting_images,
        'recommended_products': recommended_products,
        'product_url': product_url,
        'paygo_application': paygo_application,
        'active_deal': active_deal,
    })


@login_required
def paygo_apply(request, slug):
    product = get_object_or_404(Product, slug=slug, available=True)
    if not product.paygo_is_available:
        messages.error(request, 'PayGo is not currently available for this product.')
        return redirect('product_detail', slug=product.slug)

    existing_application = PayGoApplication.objects.filter(
        customer=request.user,
        product=product,
    ).exclude(status__in=['rejected', 'cancelled', 'completed']).order_by('-created_at').first()
    if existing_application:
        messages.info(request, 'You already have an active PayGo request for this product.')
        return redirect('paygo_detail', application_id=existing_application.id)

    if request.method == 'POST':
        form = PayGoApplicationForm(request.POST, user=request.user)
        form.instance.product = product
        form.instance.customer = request.user
        if form.is_valid():
            application = form.save(commit=False)
            application.product = product
            application.customer = request.user
            application.requested_price = product.price
            application.deposit_required = product.paygo_min_deposit_amount
            application.term_months = product.paygo_term_months
            application.outstanding_balance = product.price
            application.save()
            messages.success(request, 'PayGo request submitted. Finance will review it and update the status here.')
            return redirect('paygo_detail', application_id=application.id)
    else:
        form = PayGoApplicationForm(user=request.user)

    return render(request, 'paygo_apply.html', {
        'product': product,
        'form': form,
    })


@login_required
def paygo_applications(request):
    applications = PayGoApplication.objects.filter(customer=request.user).select_related('product').prefetch_related('repayments')
    return render(request, 'paygo_applications.html', {
        'applications': applications,
    })


@login_required
def paygo_detail(request, application_id):
    application = get_object_or_404(
        PayGoApplication.objects.select_related('product', 'approved_by').prefetch_related('repayments'),
        id=application_id,
        customer=request.user,
    )
    return render(request, 'paygo_detail.html', {
        'application': application,
    })


@login_required
def deal_start(request, slug):
    product = get_object_or_404(Product, slug=slug, available=True)
    if product.stock <= 0:
        messages.error(request, 'This product is out of stock.')
        return redirect('product_detail', slug=product.slug)

    existing_deal = DealRequest.objects.filter(
        customer=request.user,
        product=product,
    ).exclude(status__in=['rejected', 'cancelled', 'converted']).order_by('-updated_at').first()
    if existing_deal:
        messages.info(request, 'You already have an open deal for this product.')
        return redirect('deal_detail', deal_id=existing_deal.id)

    if request.method == 'POST':
        form = DealRequestForm(request.POST, product=product)
        if form.is_valid():
            deal = form.save(commit=False)
            deal.product = product
            deal.customer = request.user
            deal.store = product.store
            deal.save()
            messages.success(request, 'Deal request sent to the merchant.')
            return redirect('deal_detail', deal_id=deal.id)
    else:
        form = DealRequestForm(product=product)

    return render(request, 'deal_start.html', {
        'product': product,
        'form': form,
    })


@login_required
def deal_list(request):
    deals = DealRequest.objects.filter(customer=request.user).select_related('product', 'store').order_by('-updated_at')
    return render(request, 'deal_list.html', {
        'deals': deals,
    })


@login_required
def deal_detail(request, deal_id):
    deal = get_object_or_404(
        DealRequest.objects.select_related('product', 'store', 'responded_by', 'converted_order'),
        id=deal_id,
        customer=request.user,
    )
    return render(request, 'deal_detail.html', {
        'deal': deal,
    })


@login_required
def deal_convert_to_checkout(request, deal_id):
    if request.method != 'POST':
        return HttpResponseForbidden('Deal checkout conversion requires POST.')
    deal = get_object_or_404(DealRequest, id=deal_id, customer=request.user)
    if not deal.is_checkout_ready:
        messages.error(request, 'This deal is not ready for checkout yet.')
        return redirect('deal_detail', deal_id=deal.id)
    if deal.product.stock < deal.quantity:
        messages.error(request, f'Only {deal.product.stock} of {deal.product.name} available.')
        return redirect('deal_detail', deal_id=deal.id)

    cart = get_or_create_cart(request)
    cart.items.exclude(source_deal=deal).delete()
    cart_item, _created = CartItem.objects.update_or_create(
        cart=cart,
        source_deal=deal,
        defaults={
            'product': deal.product,
            'variant': None,
            'quantity': deal.quantity,
            'negotiated_price': deal.agreed_price,
        },
    )
    messages.success(request, f'Deal #{deal.id} is ready in checkout at K{cart_item.subtotal:.2f}.')
    return redirect('checkout')


@merchant_required
def merchant_dashboard(request):
    owner_profile = getattr(request.user, 'store_owner_profile', None)
    stores = list(Store.objects.filter(owner=owner_profile)) if owner_profile else []
    products = Product.objects.filter(store__in=stores).select_related('store', 'category', 'brand')
    orders = Order.objects.filter(items__product__store__in=stores).prefetch_related('items__product').distinct()
    paid_items = list(_merchant_paid_order_items(stores))
    payouts = list(_sync_merchant_payouts(stores))
    open_deals = DealRequest.objects.filter(store__in=stores).exclude(status__in=['rejected', 'cancelled', 'converted']).select_related('customer', 'product', 'store').order_by('-updated_at')

    total_revenue = _merchant_item_total(paid_items)
    ready_for_payout = _merchant_net_payout_total(
        payout for payout in payouts
        if payout.status == 'ready'
    )
    low_stock_count = products.filter(stock__lte=F('low_stock_threshold')).count()

    return render(request, 'store_dashboard.html', {
        'stores': stores,
        'products': list(products.order_by('-updated')[:12]),
        'orders': list(orders.order_by('-created')[:6]),
        'store_count': len(stores),
        'product_count': products.count(),
        'order_count': orders.count(),
        'low_stock_count': low_stock_count,
        'total_revenue': total_revenue,
        'ready_for_payout': ready_for_payout,
        'open_deal_count': open_deals.count(),
        'recent_deals': list(open_deals[:5]),
    })


def _merchant_stores_for_user(user):
    owner_profile = getattr(user, 'store_owner_profile', None)
    return Store.objects.filter(owner=owner_profile) if owner_profile else Store.objects.none()


def _merchant_orders_for_stores(stores):
    return Order.objects.filter(items__product__store__in=stores).prefetch_related('items__product').distinct()


def _merchant_order_items(order, stores):
    return order.items.filter(product__store__in=stores).select_related('product')


def _merchant_paid_order_items(stores):
    return OrderItem.objects.filter(
        product__store__in=stores,
        order__payment_status='completed',
    ).select_related('order', 'product', 'product__store').order_by('-order__created')


def _merchant_item_total(items):
    return sum(item.price * item.quantity for item in items)


def _merchant_payout_total(payouts):
    return sum(payout.amount for payout in payouts)


def _merchant_net_payout_total(payouts):
    return sum(payout.net_amount for payout in payouts)


def _merchant_platform_fee_total(payouts):
    return sum(payout.platform_fee for payout in payouts)


def _merchant_payout_queryset(stores):
    return MerchantPayout.objects.filter(store__in=stores).select_related(
        'store',
        'batch',
        'order_item__order',
        'order_item__product',
    ).order_by('-created_at')


def _merchant_deal_queryset(stores):
    return DealRequest.objects.filter(store__in=stores).select_related(
        'customer',
        'product',
        'store',
        'responded_by',
    ).order_by('-updated_at')


@merchant_required
def merchant_deals(request):
    stores = _merchant_stores_for_user(request.user)
    deals = _merchant_deal_queryset(stores)
    return render(request, 'merchant_deals.html', {
        'deals': deals,
    })


@merchant_required
def merchant_deal_detail(request, deal_id):
    stores = _merchant_stores_for_user(request.user)
    deal = get_object_or_404(_merchant_deal_queryset(stores), id=deal_id)
    if request.method == 'POST':
        form = MerchantDealResponseForm(request.POST, instance=deal)
        if form.is_valid():
            action = form.cleaned_data['action']
            if action == 'accept':
                deal.accept(
                    request.user,
                    agreed_price=form.cleaned_data['agreed_price'],
                    agreed_terms=form.cleaned_data.get('agreed_terms', ''),
                    response=form.cleaned_data.get('merchant_response', ''),
                )
                messages.success(request, f'Deal #{deal.id} accepted.')
            elif action == 'counter':
                deal.counter(
                    request.user,
                    agreed_price=form.cleaned_data['agreed_price'],
                    agreed_terms=form.cleaned_data.get('agreed_terms', ''),
                    response=form.cleaned_data.get('merchant_response', ''),
                )
                messages.success(request, f'Deal #{deal.id} countered.')
            elif action == 'reject':
                deal.reject(request.user, response=form.cleaned_data.get('merchant_response', ''))
                messages.success(request, f'Deal #{deal.id} rejected.')
            return redirect('merchant_deal_detail', deal_id=deal.id)
    else:
        form = MerchantDealResponseForm(initial={
            'action': 'accept',
            'agreed_price': deal.agreed_price or deal.offered_price,
            'agreed_terms': deal.agreed_terms or deal.customer_terms,
        }, instance=deal)

    return render(request, 'merchant_deal_detail.html', {
        'deal': deal,
        'form': form,
    })


def _sync_merchant_payouts(stores):
    for item in _merchant_paid_order_items(stores):
        payout, _created = MerchantPayout.objects.get_or_create(
            order_item=item,
            defaults={
                'store': item.product.store,
                'amount': item.subtotal,
                'net_amount': item.subtotal,
            },
        )
        payout.refresh_from_order()
    return _merchant_payout_queryset(stores)


def _finance_payout_queryset():
    return MerchantPayout.objects.select_related(
        'store',
        'batch',
        'order_item__order',
        'order_item__product',
    ).order_by('-created_at')


def _sync_all_payouts():
    stores = Store.objects.all()
    _sync_merchant_payouts(stores)
    return _finance_payout_queryset()


def _filtered_finance_payouts(request):
    payouts = _sync_all_payouts()
    status_filter = request.GET.get('status') or ''
    store_filter = request.GET.get('store') or ''
    query = (request.GET.get('q') or '').strip()

    if status_filter:
        payouts = payouts.filter(status=status_filter)
    if store_filter and store_filter.isdigit():
        payouts = payouts.filter(store_id=store_filter)
    if query:
        payout_filters = (
            Q(store__name__icontains=query) |
            Q(order_item__product__name__icontains=query) |
            Q(order_item__order__first_name__icontains=query) |
            Q(order_item__order__last_name__icontains=query) |
            Q(order_item__order__email__icontains=query) |
            Q(order_item__order__payment_reference__icontains=query)
        )
        if query.isdigit():
            payout_filters |= Q(order_item__order__id=int(query))
        payouts = payouts.filter(payout_filters)

    return payouts, {
        'status': status_filter,
        'store': store_filter,
        'q': query,
    }


def _payout_csv_response(payouts, filename='merchant-payouts.csv'):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([
        'Payout ID',
        'Store',
        'Order',
        'Product',
        'Quantity',
        'Gross Amount',
        'Platform Fee',
        'Net Payout',
        'Status',
        'Payout Batch',
        'Paid At',
        'Payment Reference',
        'Customer Email',
    ])
    for payout in payouts:
        order = payout.order_item.order
        writer.writerow([
            payout.id,
            payout.store.name,
            order.id,
            payout.order_item.product.name,
            payout.order_item.quantity,
            f'{payout.amount:.2f}',
            f'{payout.platform_fee:.2f}',
            f'{payout.net_amount:.2f}',
            payout.get_status_display(),
            payout.batch.reference if payout.batch else '',
            payout.paid_at.isoformat() if payout.paid_at else '',
            order.payment_reference or '',
            order.email,
        ])
    return response


def _create_payout_batch(selected, user, reference, note):
    payable = list(selected.filter(status__in=['ready', 'held']).select_related('order_item__order', 'order_item__product', 'store'))
    if not payable:
        return None

    paid_at = timezone.now()
    batch = PayoutBatch.objects.create(
        reference=reference,
        processed_by=user,
        gross_total=_merchant_payout_total(payable),
        platform_fee_total=_merchant_platform_fee_total(payable),
        net_total=_merchant_net_payout_total(payable),
        note=note,
        paid_at=paid_at,
    )
    for payout in payable:
        payout.status = 'paid'
        payout.paid_at = paid_at
        payout.batch = batch
        payout.save(update_fields=['status', 'paid_at', 'batch', 'updated_at'])
    return batch


@finance_admin_required
def finance_payouts(request):
    payouts, filters = _filtered_finance_payouts(request)

    if request.method == 'POST':
        action = request.POST.get('action')
        selected_ids = request.POST.getlist('payout_ids')
        selected = _finance_payout_queryset().filter(id__in=selected_ids)

        if not selected_ids:
            messages.error(request, 'Select at least one payout record.')
            return redirect('finance_payouts')

        if action == 'mark_paid':
            reference = (request.POST.get('batch_reference') or '').strip()
            note = (request.POST.get('batch_note') or '').strip()
            if not reference:
                messages.error(request, 'Enter a payout batch reference before marking payouts paid.')
                return redirect('finance_payouts')
            if PayoutBatch.objects.filter(reference=reference).exists():
                messages.error(request, 'That payout batch reference already exists.')
                return redirect('finance_payouts')
            batch = _create_payout_batch(selected, request.user, reference, note)
            if not batch:
                messages.error(request, 'Only ready or held payout records can be batched as paid.')
                return redirect('finance_payouts')
            messages.success(request, f'Created payout batch {batch.reference} for K{batch.net_total:.2f}.')
        elif action == 'hold':
            updated = selected.exclude(status='paid').update(status='held', paid_at=None)
            messages.success(request, f'Held {updated} payout record(s) for review.')
        elif action == 'refresh':
            updated = 0
            for payout in selected:
                payout.refresh_from_order()
                updated += 1
            messages.success(request, f'Refreshed {updated} payout record(s).')
        else:
            messages.error(request, 'Choose a valid payout action.')
        return redirect('finance_payouts')

    if request.GET.get('export') == 'csv':
        return _payout_csv_response(payouts)

    payout_list = list(payouts[:200])
    all_payouts = list(_sync_all_payouts())

    return render(request, 'finance_payouts.html', {
        'payouts': payout_list,
        'stores': Store.objects.order_by('name'),
        'filters': filters,
        'status_choices': MerchantPayout.STATUS_CHOICES,
        'gross_total': _merchant_payout_total(all_payouts),
        'platform_fee_total': _merchant_platform_fee_total(all_payouts),
        'ready_total': _merchant_net_payout_total(payout for payout in all_payouts if payout.status == 'ready'),
        'pending_total': _merchant_net_payout_total(payout for payout in all_payouts if payout.status == 'pending'),
        'paid_total': _merchant_net_payout_total(payout for payout in all_payouts if payout.status == 'paid'),
        'held_total': _merchant_net_payout_total(payout for payout in all_payouts if payout.status == 'held'),
        'filtered_total': _merchant_net_payout_total(payout_list),
        'recent_batches': PayoutBatch.objects.select_related('processed_by')[:8],
    })


@finance_admin_required
def finance_payout_batch_detail(request, batch_id):
    batch = get_object_or_404(PayoutBatch.objects.select_related('processed_by'), id=batch_id)
    payouts = batch.payouts.select_related(
        'store',
        'batch',
        'order_item__order',
        'order_item__product',
    ).order_by('store__name', 'order_item__order_id')

    if request.GET.get('export') == 'csv':
        return _payout_csv_response(payouts, f'payout-batch-{batch.reference}.csv')

    payout_list = list(payouts)

    return render(request, 'finance_payout_batch_detail.html', {
        'batch': batch,
        'payouts': payout_list,
        'payout_count': len(payout_list),
        'gross_total': _merchant_payout_total(payout_list),
        'platform_fee_total': _merchant_platform_fee_total(payout_list),
        'net_total': _merchant_net_payout_total(payout_list),
    })


def _supporting_image_ids_to_delete(request):
    ids = []
    for value in request.POST.getlist('delete_supporting_images'):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _prepare_supporting_images(request, product=None):
    delete_ids = _supporting_image_ids_to_delete(request)
    uploaded_images = request.FILES.getlist('supporting_images')
    current_count = 0
    if product:
        current_count = product.supporting_images.exclude(id__in=delete_ids).count()

    if current_count + len(uploaded_images) > MAX_SUPPORTING_PRODUCT_IMAGES:
        raise ValidationError(f'Keep each product gallery to {MAX_SUPPORTING_PRODUCT_IMAGES} supporting images.')

    return delete_ids, [prepare_product_image(image) for image in uploaded_images]


def _save_supporting_images(product, delete_ids, prepared_images):
    if delete_ids:
        product.supporting_images.filter(id__in=delete_ids).delete()
    for image in prepared_images:
        ProductImage.objects.create(product=product, image=image)


def _product_submit_state(request):
    return request.POST.get('submit_action') or 'publish'


def _apply_product_publication_state(product, submit_state):
    if submit_state == 'draft':
        product.publication_status = 'draft'
        product.available = False
    else:
        product.publication_status = 'published'
        product.available = product.available and product.stock > 0
    return product


def _unique_product_slug(name, current_product=None):
    base_slug = slugify(name) or f"product-{get_random_string(6)}"
    slug = base_slug
    suffix = 2
    queryset = Product.objects.all()
    if current_product:
        queryset = queryset.exclude(pk=current_product.pk)
    while queryset.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


@merchant_required
def merchant_orders(request):
    stores = _merchant_stores_for_user(request.user)
    orders = list(_merchant_orders_for_stores(stores).order_by('-created'))
    for order in orders:
        order.merchant_items = list(_merchant_order_items(order, stores))
        order.merchant_total = sum(item.price * item.quantity for item in order.merchant_items)
        order.merchant_product_details = ', '.join(
            f'{item.product.name} (x{item.quantity})'
            for item in order.merchant_items
        )

    return render(request, 'merchant_orders.html', {
        'orders': orders,
        'store_count': stores.count(),
    })


@merchant_required
def merchant_payouts(request):
    stores = _merchant_stores_for_user(request.user)
    payouts = list(_sync_merchant_payouts(stores))

    return render(request, 'merchant_payouts.html', {
        'store_count': stores.count(),
        'payouts': payouts,
        'gross_paid_total': _merchant_payout_total(payouts),
        'platform_fee_total': _merchant_platform_fee_total(payouts),
        'ready_for_payout': _merchant_net_payout_total(payout for payout in payouts if payout.status == 'ready'),
        'pending_fulfillment_total': _merchant_net_payout_total(payout for payout in payouts if payout.status == 'pending'),
        'paid_out_total': _merchant_net_payout_total(payout for payout in payouts if payout.status == 'paid'),
        'held_total': _merchant_net_payout_total(payout for payout in payouts if payout.status == 'held'),
    })


@merchant_required
def merchant_order_detail(request, order_id):
    stores = _merchant_stores_for_user(request.user)
    order = get_object_or_404(_merchant_orders_for_stores(stores), id=order_id)
    merchant_items = _merchant_order_items(order, stores)
    merchant_total = sum(item.price * item.quantity for item in merchant_items)

    return render(request, 'merchant_order_detail.html', {
        'order': order,
        'merchant_items': merchant_items,
        'merchant_total': merchant_total,
    })


@merchant_required
def merchant_order_update(request, order_id):
    if request.method != 'POST':
        return HttpResponseForbidden('Order updates require POST.')

    stores = _merchant_stores_for_user(request.user)
    order = get_object_or_404(_merchant_orders_for_stores(stores), id=order_id)
    action = request.POST.get('action')

    if action == 'save_fulfillment':
        order.dispatch_reference = (request.POST.get('dispatch_reference') or '').strip()[:120]
        order.fulfillment_notes = (request.POST.get('fulfillment_notes') or '').strip()
        order.save(update_fields=['dispatch_reference', 'fulfillment_notes'])
        messages.success(request, f'Fulfillment details saved for Order #{order.id}.')
    elif action == 'mark_packing':
        if order.payment_status != 'completed' and not order.payment_confirmed:
            messages.error(request, f'Order #{order.id} must be paid before packing.')
        elif order.status in {'pending', 'payment_awaiting', 'paid'}:
            order.status = 'packing'
            order.save(update_fields=['status'])
            messages.success(request, f'Order #{order.id} marked as packing.')
        else:
            messages.info(request, f'Order #{order.id} is already {order.get_status_display().lower()}.')
    elif action == 'mark_dispatched':
        if order.status != 'packing':
            messages.error(request, f'Order #{order.id} must be packing before dispatch.')
        else:
            order.status = 'dispatched'
            order.dispatch_reference = (request.POST.get('dispatch_reference') or order.dispatch_reference or '').strip()[:120]
            order.fulfillment_notes = (request.POST.get('fulfillment_notes') or order.fulfillment_notes or '').strip()
            order.save(update_fields=['status', 'dispatch_reference', 'fulfillment_notes'])
            messages.success(request, f'Order #{order.id} marked as dispatched.')
    else:
        messages.error(request, 'Unknown order action.')

    return redirect(request.POST.get('next') or 'merchant_orders')


def _delivery_orders_for_user(user):
    return Order.objects.filter(
        Q(status='dispatched') | Q(status='delivered', delivery_partner=user),
        Q(delivery_partner__isnull=True) | Q(delivery_partner=user),
    ).prefetch_related('items__product').select_related('delivery_partner', 'delivery_confirmed_by').order_by('-updated')


@delivery_partner_required
def delivery_orders(request):
    orders = list(_delivery_orders_for_user(request.user))
    available_orders = [order for order in orders if order.status == 'dispatched' and not order.delivery_partner_id]
    assigned_orders = [order for order in orders if order.delivery_partner_id == request.user.id and order.status == 'dispatched']
    completed_orders = [order for order in orders if order.delivery_partner_id == request.user.id and order.status == 'delivered']

    return render(request, 'delivery_orders.html', {
        'orders': orders,
        'available_count': len(available_orders),
        'assigned_count': len(assigned_orders),
        'completed_count': len(completed_orders),
    })


@delivery_partner_required
def delivery_order_update(request, order_id):
    if request.method != 'POST':
        return HttpResponseForbidden('Delivery updates require POST.')

    order = get_object_or_404(Order, id=order_id)
    action = request.POST.get('action')

    if action == 'claim':
        if order.status != 'dispatched':
            messages.error(request, f'Order #{order.id} is not ready for delivery.')
        elif order.delivery_partner_id and order.delivery_partner_id != request.user.id:
            messages.error(request, f'Order #{order.id} is already assigned.')
        else:
            order.delivery_partner = request.user
            order.save(update_fields=['delivery_partner'])
            messages.success(request, f'Order #{order.id} assigned to you.')
    elif action == 'mark_delivered':
        if order.delivery_partner_id != request.user.id:
            messages.error(request, f'Claim order #{order.id} before marking it delivered.')
        elif order.status != 'dispatched':
            messages.error(request, f'Order #{order.id} cannot be marked delivered from its current status.')
        else:
            order.status = 'delivered'
            order.delivered_at = timezone.now()
            order.delivery_confirmed_by = request.user
            order.delivery_notes = (request.POST.get('delivery_notes') or order.delivery_notes or '').strip()
            order.save(update_fields=['status', 'delivered_at', 'delivery_confirmed_by', 'delivery_notes'])
            messages.success(request, f'Order #{order.id} marked as delivered.')
    else:
        messages.error(request, 'Choose a valid delivery action.')

    return redirect('delivery_orders')


@merchant_required
def merchant_product_create(request):
    owner_profile = getattr(request.user, 'store_owner_profile', None)
    stores = Store.objects.filter(owner=owner_profile) if owner_profile else Store.objects.none()

    if request.method == 'POST':
        form = MerchantProductForm(request.POST, request.FILES, stores=stores)
        try:
            delete_ids, supporting_images = _prepare_supporting_images(request)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if form.is_valid():
                product = form.save(commit=False)
                _apply_product_publication_state(product, _product_submit_state(request))
                product.save()
                form.save_m2m()
                _save_supporting_images(product, delete_ids, supporting_images)
                if product.is_published:
                    messages.success(request, 'Product published.')
                else:
                    messages.success(request, 'Product saved as a draft.')
                return redirect('merchant_dashboard')
    else:
        form = MerchantProductForm(stores=stores)

    return render(request, 'merchant_product_form.html', {
        'form': form,
        'has_stores': stores.exists(),
        'mode': 'create',
        'max_supporting_images': MAX_SUPPORTING_PRODUCT_IMAGES,
    })


@merchant_required
def merchant_product_edit(request, product_id):
    owner_profile = getattr(request.user, 'store_owner_profile', None)
    stores = Store.objects.filter(owner=owner_profile) if owner_profile else Store.objects.none()
    product = get_object_or_404(Product, id=product_id, store__in=stores)

    if request.method == 'POST':
        form = MerchantProductForm(request.POST, request.FILES, stores=stores, require_image=False, instance=product)
        try:
            delete_ids, supporting_images = _prepare_supporting_images(request, product)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if form.is_valid():
                product = form.save(commit=False)
                _apply_product_publication_state(product, _product_submit_state(request))
                product.save()
                form.save_m2m()
                _save_supporting_images(product, delete_ids, supporting_images)
                if product.is_published:
                    messages.success(request, 'Product updated.')
                else:
                    messages.success(request, 'Product saved as a draft.')
                return redirect('merchant_dashboard')
    else:
        form = MerchantProductForm(stores=stores, require_image=False, instance=product)

    return render(request, 'merchant_product_form.html', {
        'form': form,
        'has_stores': stores.exists(),
        'mode': 'edit',
        'product': product,
        'supporting_images': product.supporting_images.all(),
        'max_supporting_images': MAX_SUPPORTING_PRODUCT_IMAGES,
    })


@merchant_required
def merchant_product_duplicate(request, product_id):
    if request.method != 'POST':
        return HttpResponseForbidden('Product duplication requires POST.')

    stores = _merchant_stores_for_user(request.user)
    source = get_object_or_404(Product.objects.select_related('store', 'category', 'brand'), id=product_id, store__in=stores)
    duplicate = Product.objects.create(
        name=f'{source.name} Copy',
        slug=_unique_product_slug(f'{source.name} Copy'),
        category=source.category,
        store=source.store,
        brand=source.brand,
        description=source.description,
        subcategory=source.subcategory,
        price=source.price,
        image=source.image,
        stock=0,
        offline_stock=source.offline_stock,
        low_stock_threshold=source.low_stock_threshold,
        publication_status='draft',
        available=False,
        show_selling_fast=False,
        season=source.season,
        fabric=source.fabric,
        color=source.color,
        cost_range=source.cost_range,
    )
    for image in source.supporting_images.all():
        ProductImage.objects.create(product=duplicate, image=image.image)
    messages.success(request, f'Draft duplicate created for {source.name}.')
    return redirect('merchant_product_edit', product_id=duplicate.id)


@merchant_required
def merchant_product_inventory_update(request, product_id):
    if request.method != 'POST':
        return HttpResponseForbidden('Inventory updates require POST.')

    stores = _merchant_stores_for_user(request.user)
    product = get_object_or_404(Product, id=product_id, store__in=stores)
    product.stock = _parse_positive_int(request.POST.get('stock'), product.stock, minimum=0)
    product.offline_stock = _parse_positive_int(request.POST.get('offline_stock'), product.offline_stock, minimum=0)
    product.low_stock_threshold = _parse_positive_int(request.POST.get('low_stock_threshold'), product.low_stock_threshold, minimum=0)
    if product.publication_status == 'published':
        product.available = product.stock > 0 and request.POST.get('available') == 'on'
    else:
        product.available = False
    product.save(update_fields=['stock', 'offline_stock', 'low_stock_threshold', 'available', 'updated'])
    messages.success(request, f'Inventory updated for {product.name}.')
    if _wants_json(request):
        return JsonResponse({
            'status': True,
            'message': f'Inventory updated for {product.name}.',
            'product': {
                'id': product.id,
                'stock': product.stock,
                'offline_stock': product.offline_stock,
                'low_stock_threshold': product.low_stock_threshold,
                'available': product.available,
                'publication_status': product.publication_status,
                'publication_label': product.get_publication_status_display(),
                'is_low_stock': product.is_low_stock,
            },
        })
    return redirect(request.POST.get('next') or 'merchant_dashboard')


@platform_admin_required
def admin_dashboard(request):
    def dashboard_redirect(mode='editor'):
        return redirect(f"{request.path}?mode={mode}")

    def update_product_from_post(product, mode='editor'):
        previous_online = product.stock
        previous_offline = product.offline_stock

        product.name = (request.POST.get('name') or product.name).strip()
        product.description = (request.POST.get('description') or '').strip()
        selected_subcategory = (request.POST.get('subcategory') or '').strip()
        custom_subcategory = _ensure_custom_subcategory(selected_subcategory)
        product.subcategory = custom_subcategory.name if custom_subcategory else selected_subcategory
        product.price = _money(request.POST.get('price') or product.price)
        product.stock = _parse_positive_int(request.POST.get('stock'), product.stock, minimum=0)
        product.offline_stock = _parse_positive_int(request.POST.get('offline_stock'), product.offline_stock, minimum=0)
        product.low_stock_threshold = _parse_positive_int(request.POST.get('low_stock_threshold'), product.low_stock_threshold, minimum=0)
        product.available = request.POST.get('available') == 'on' and product.stock > 0
        product.show_selling_fast = request.POST.get('show_selling_fast') == 'on'
        if 'color' in request.POST:
            product.color = (request.POST.get('color') or '').strip() or None
        if 'season' in request.POST:
            product.season = request.POST.get('season') or None
        if 'fabric' in request.POST:
            product.fabric = request.POST.get('fabric') or None
        if 'cost_range' in request.POST:
            product.cost_range = request.POST.get('cost_range') or None

        category_id = request.POST.get('category')
        if category_id:
            product.category = get_object_or_404(Category, id=category_id)

        brand_id = request.POST.get('brand')
        product.brand = Brand.objects.filter(id=brand_id).first() if brand_id else None

        uploaded_image = request.FILES.get('image')
        existing_image = (request.POST.get('existing_image') or '').strip()
        if uploaded_image:
            product.image = uploaded_image
        elif existing_image:
            product.image = existing_image

        if not product.slug:
            base_slug = slugify(product.name) or f"product-{product.id or get_random_string(6)}"
            slug = base_slug
            suffix = 2
            while Product.objects.filter(slug=slug).exclude(id=product.id).exists():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            product.slug = slug

        product.save()

        for supporting_image in request.FILES.getlist('supporting_images'):
            ProductImage.objects.create(product=product, image=supporting_image)

        if product.stock != previous_online or product.offline_stock != previous_offline:
            StockAdjustment.objects.create(
                product=product,
                user=request.user,
                previous_online_stock=previous_online,
                new_online_stock=product.stock,
                previous_offline_stock=previous_offline,
                new_offline_stock=product.offline_stock,
                reason=(request.POST.get('reason') or f'{mode.title()} update').strip(),
            )

        return product

    analytic_labels = {
        'products': 'Products',
        'low_stock': 'Low stock',
        'out_of_stock': 'Out of stock',
        'open_orders': 'Open orders',
        'paid_orders': 'Paid orders',
        'revenue': 'Revenue',
    }

    def current_analytic_value(key):
        if key == 'products':
            return Decimal(Product.objects.count())
        if key == 'low_stock':
            return Decimal(sum(1 for product in Product.objects.all() if product.is_low_stock))
        if key == 'out_of_stock':
            return Decimal(Product.objects.filter(stock=0).count())
        if key == 'open_orders':
            return Decimal(Order.objects.exclude(status__in=['delivered', 'cancelled', 'cleared', 'refunded']).count())
        if key == 'paid_orders':
            return Decimal(Order.objects.filter(Q(payment_status='completed') | Q(payment_confirmed=True)).count())
        if key == 'revenue':
            return Order.objects.filter(Q(payment_status='completed') | Q(payment_confirmed=True)).aggregate(earnings=Sum('total'))['earnings'] or Decimal('0')
        return Decimal('0')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_stock':
            product = get_object_or_404(Product, id=request.POST.get('product_id'))
            previous_online = product.stock
            previous_offline = product.offline_stock
            product.stock = _parse_positive_int(request.POST.get('stock'), 0, minimum=0)
            product.offline_stock = _parse_positive_int(request.POST.get('offline_stock'), 0, minimum=0)
            product.low_stock_threshold = _parse_positive_int(request.POST.get('low_stock_threshold'), 0, minimum=0)
            product.available = request.POST.get('available') == 'on' and product.stock > 0
            product.save(update_fields=['stock', 'offline_stock', 'low_stock_threshold', 'available', 'updated'])
            StockAdjustment.objects.create(
                product=product,
                user=request.user,
                previous_online_stock=previous_online,
                new_online_stock=product.stock,
                previous_offline_stock=previous_offline,
                new_offline_stock=product.offline_stock,
                reason=(request.POST.get('reason') or 'Dashboard update').strip(),
            )
            messages.success(request, f"Updated stock for {product.name}.")
            return dashboard_redirect('stock')

        if action == 'update_product':
            product = get_object_or_404(Product, id=request.POST.get('product_id'))
            update_product_from_post(product, 'editor')
            messages.success(request, f"Updated storefront item: {product.name}.")
            return dashboard_redirect('editor')

        if action == 'delete_product':
            product = get_object_or_404(Product, id=request.POST.get('product_id'))
            product_name = product.name
            product.delete()
            messages.success(request, f"Deleted {product_name} from the database.")
            return dashboard_redirect('editor')

        if action == 'reset_analytic':
            analytic_key = request.POST.get('analytic_key') or ''
            if analytic_key not in analytic_labels:
                messages.error(request, 'Unknown analytic.')
                return dashboard_redirect(request.POST.get('mode') or 'editor')
            DashboardAnalyticReset.objects.update_or_create(
                key=analytic_key,
                defaults={
                    'label': analytic_labels[analytic_key],
                    'baseline_value': current_analytic_value(analytic_key),
                    'reset_by': request.user,
                },
            )
            messages.success(request, f"Reset {analytic_labels[analytic_key]} analytic.")
            return dashboard_redirect(request.POST.get('mode') or 'editor')

        if action == 'create_subcategory':
            subcategory_name = (request.POST.get('subcategory_name') or '').strip()
            subcategory_slug = _normalize_filter_slug(subcategory_name)
            if not subcategory_name or not subcategory_slug:
                messages.error(request, 'Enter a filter type name.')
            elif subcategory_slug in CORE_STOREFRONT_FILTER_SLUGS:
                messages.info(request, f"{subcategory_name} is already a built-in filter type.")
            else:
                subcategory, created = ProductSubcategory.objects.get_or_create(
                    slug=subcategory_slug,
                    defaults={'name': subcategory_name},
                )
                if created:
                    messages.success(request, f"Added {subcategory.name} to the filter type list.")
                else:
                    messages.info(request, f"{subcategory.name} is already in the filter type list.")
            return dashboard_redirect('editor')

        if action == 'delete_subcategory':
            subcategory = get_object_or_404(ProductSubcategory, id=request.POST.get('subcategory_id'))
            subcategory_name = subcategory.name
            Product.objects.filter(
                Q(subcategory__iexact=subcategory_name) |
                Q(subcategory__iexact=subcategory.slug)
            ).update(subcategory='')
            subcategory.delete()
            messages.success(request, f"Removed {subcategory_name} from filter types and cleared it from matching products.")
            return dashboard_redirect('editor')

        if action == 'create_cashier':
            name = (request.POST.get('cashier_name') or '').strip()
            email = (request.POST.get('cashier_email') or '').strip().lower()
            phone = _normalize_phone(request.POST.get('cashier_phone') or '')
            if not name or not email or not phone:
                messages.error(request, 'Cashier name, email, and phone are required.')
                return dashboard_redirect('cashiers')
            CashierContact.objects.create(name=name, email=email, phone=phone, active=True)
            messages.success(request, f"Added cashier contact {name}.")
            return dashboard_redirect('cashiers')

        if action == 'update_cashier':
            contact = get_object_or_404(CashierContact, id=request.POST.get('cashier_id'))
            contact.name = (request.POST.get('cashier_name') or contact.name).strip()
            contact.email = (request.POST.get('cashier_email') or contact.email).strip().lower()
            contact.phone = _normalize_phone(request.POST.get('cashier_phone') or contact.phone)
            contact.active = request.POST.get('active') == 'on'
            contact.save()
            messages.success(request, f"Updated cashier contact {contact.name}.")
            return dashboard_redirect('cashiers')

        if action == 'delete_cashier':
            contact = get_object_or_404(CashierContact, id=request.POST.get('cashier_id'))
            contact_name = contact.name
            contact.delete()
            messages.success(request, f"Removed cashier contact {contact_name}.")
            return dashboard_redirect('cashiers')

        if action == 'create_payment_info':
            title = (request.POST.get('payment_title') or '').strip()
            number = (request.POST.get('payment_number') or '').strip()
            recipient_name = (request.POST.get('recipient_name') or '').strip()
            sort_order = _parse_positive_int(request.POST.get('sort_order'), 0, minimum=0)
            if not title or not number or not recipient_name:
                messages.error(request, 'Payment title, number, and recipient/receiver name are required.')
                return dashboard_redirect('cashiers')
            PaymentInfo.objects.create(
                title=title,
                number=number,
                recipient_name=recipient_name,
                sort_order=sort_order,
                active=request.POST.get('active') == 'on',
            )
            messages.success(request, f"Added payment info {title}.")
            return dashboard_redirect('cashiers')

        if action == 'update_payment_info':
            payment_info = get_object_or_404(PaymentInfo, id=request.POST.get('payment_info_id'))
            payment_info.title = (request.POST.get('payment_title') or payment_info.title).strip()
            payment_info.number = (request.POST.get('payment_number') or payment_info.number).strip()
            payment_info.recipient_name = (request.POST.get('recipient_name') or payment_info.recipient_name).strip()
            payment_info.sort_order = _parse_positive_int(request.POST.get('sort_order'), payment_info.sort_order, minimum=0)
            payment_info.active = request.POST.get('active') == 'on'
            payment_info.save()
            messages.success(request, f"Updated payment info {payment_info.title}.")
            return dashboard_redirect('cashiers')

        if action == 'delete_payment_info':
            payment_info = get_object_or_404(PaymentInfo, id=request.POST.get('payment_info_id'))
            title = payment_info.title
            payment_info.delete()
            messages.success(request, f"Removed payment info {title}.")
            return dashboard_redirect('cashiers')

        if action == 'create_social_link':
            label = (request.POST.get('social_label') or '').strip()
            url = (request.POST.get('social_url') or '').strip()
            sort_order = _parse_positive_int(request.POST.get('sort_order'), 0, minimum=0)
            if not label:
                messages.error(request, 'Enter a social name.')
                return dashboard_redirect('footer')
            SocialLink.objects.create(
                label=label,
                url=url,
                sort_order=sort_order,
                active=request.POST.get('active') == 'on' and bool(url),
            )
            messages.success(request, f"Added social link {label}.")
            return dashboard_redirect('footer')

        if action == 'update_social_link':
            social_link = get_object_or_404(SocialLink, id=request.POST.get('social_id'))
            social_link.label = (request.POST.get('social_label') or social_link.label).strip()
            social_link.url = (request.POST.get('social_url') or '').strip()
            social_link.sort_order = _parse_positive_int(request.POST.get('sort_order'), social_link.sort_order, minimum=0)
            social_link.active = request.POST.get('active') == 'on' and bool(social_link.url)
            social_link.save()
            messages.success(request, f"Updated social link {social_link.label}.")
            return dashboard_redirect('footer')

        if action == 'delete_social_link':
            social_link = get_object_or_404(SocialLink, id=request.POST.get('social_id'))
            label = social_link.label
            social_link.delete()
            messages.success(request, f"Removed social link {label}.")
            return dashboard_redirect('footer')

        if action == 'update_storefront_control':
            control = StorefrontControl.objects.first() or StorefrontControl.objects.create()
            header_mode = request.POST.get('header_mode') or 'interactive'
            control.header_mode = header_mode if header_mode in {'interactive', 'banner'} else 'interactive'
            control.new_in_message = (
                request.POST.get('new_in_message')
                or 'Fresh styles, latest arrivals, and new products added to the storefront.'
            ).strip()
            control.today_new_in_message = (
                request.POST.get('today_new_in_message')
                or control.new_in_message
                or 'Fresh styles, latest arrivals, and new products added to the storefront.'
            ).strip()
            uploaded_banner = request.FILES.get('header_banner')
            if uploaded_banner:
                control.header_banner = uploaded_banner
            control.save()
            for category in Category.objects.all():
                category_message = request.POST.get(f'category_message_{category.id}')
                if category_message is not None:
                    category.new_in_message = category_message.strip()
                    category.save(update_fields=['new_in_message'])
            messages.success(request, 'Updated Header and ADs controls.')
            return dashboard_redirect('header_ads')

        if action == 'create_product':
            store = Product.objects.exclude(store__isnull=True).values_list('store_id', flat=True).first()
            default_store = Store.objects.filter(id=store).first() if store else Store.objects.first()
            category = Category.objects.filter(id=request.POST.get('category')).first() or Category.objects.first()
            if not default_store or not category:
                messages.error(request, 'Create a store and category before adding products.')
                return dashboard_redirect('editor')

            product = Product(store=default_store, category=category, name='New product', price=Decimal('0.00'), image='products/WhatsApp_Image_2025-03-20_at_15.52.43_9e937bc2.jpg')
            update_product_from_post(product, 'editor')
            messages.success(request, f"Added storefront item: {product.name}.")
            return dashboard_redirect('editor')

        if action == 'update_order':
            order = get_object_or_404(Order, id=request.POST.get('order_id'))
            old_status = order.status
            old_payment_status = order.payment_status
            cashier_step = request.POST.get('cashier_step') or ''

            if cashier_step == 'money_received':
                try:
                    with transaction.atomic():
                        order.payment_status = 'completed'
                        order.payment_confirmed = True
                        order.status = 'packing'
                        order.save(update_fields=['payment_status', 'payment_confirmed', 'status'])
                        _deduct_stock_for_order(order)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return dashboard_redirect('cashier')
                try:
                    send_order_confirmation_email(order)
                except Exception:
                    logger.exception('Payment confirmation email failed for Order ID %s', order.id)
                _send_cashier_order_message(
                    order,
                    _payment_confirmed_receipt_message(order),
                )
                messages.success(request, f"Money received for Order #{order.id}. Customer payment confirmation is now live.")
                return dashboard_redirect('cashier')

            if cashier_step == 'en_route':
                order.status = 'dispatched'
                order.save(update_fields=['status'])
                _send_cashier_order_message(
                    order,
                    f"Order #{order.id} is en route. Items: {order.product_details()}. Reply or call us if you have questions.",
                )
                messages.success(request, f"Order #{order.id} marked en route.")
                return dashboard_redirect('cashier')

            if cashier_step == 'arrived':
                order.status = 'delivered'
                order.delivered_at = timezone.now()
                order.save(update_fields=['status', 'delivered_at'])
                _send_cashier_order_message(
                    order,
                    f"Order #{order.id} has arrived. A cashier will call you with pickup or handover details. Thank you.",
                )
                messages.success(request, f"Order #{order.id} marked arrived.")
                return dashboard_redirect('cashier')

            if cashier_step == 'cancel_order':
                order.status = 'cancelled'
                if order.payment_status not in ('completed', 'refunded'):
                    order.payment_status = 'failed'
                order.save(update_fields=['status', 'payment_status'])
                _send_cashier_order_message(
                    order,
                    f"Order #{order.id} has been cancelled. Please reply or call us if you need help placing a new order.",
                )
                messages.success(request, f"Order #{order.id} cancelled.")
                return dashboard_redirect('cashier')

            if cashier_step == 'clear_order':
                order.status = 'cleared'
                order.save(update_fields=['status'])
                messages.success(request, f"Order #{order.id} cleared from cashier mode.")
                return dashboard_redirect('cashier')

            order.status = request.POST.get('status') or order.status
            order.payment_status = request.POST.get('payment_status') or order.payment_status
            order.notes = (request.POST.get('notes') or '').strip()
            if order.status == 'delivered' and not order.delivered_at:
                order.delivered_at = timezone.now()
            order.save()

            if order.payment_status == 'completed' and old_payment_status != 'completed':
                try:
                    _set_order_paid(order)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect('admin_dashboard')

            if order.status == 'dispatched' and old_status != 'dispatched':
                _send_cashier_order_message(
                    order,
                    f"Order #{order.id} is en route. Items: {order.product_details()}. Reply or call us if you have questions.",
                )
            elif order.status == 'delivered' and old_status != 'delivered':
                _send_cashier_order_message(
                    order,
                    f"Order #{order.id} has arrived. A cashier will call you with pickup or handover details. Thank you.",
                )

            messages.success(request, f"Updated Order #{order.id}.")
            return dashboard_redirect('cashier')

    total_conversations = BotConversation.objects.count()
    total_learned_keywords = LearnedKeyword.objects.count()
    total_products_raw = Product.objects.count()
    total_categories = Category.objects.count()
    total_brands = Brand.objects.count()
    total_users = get_user_model().objects.filter(is_active=True)
    new_users = total_users.filter(date_joined__gte=timezone.now() - timedelta(days=30)).count()
    old_users = total_users.filter(date_joined__lt=timezone.now() - timedelta(days=30)).count()
    active_users_last_30_days = total_users.filter(last_login__gte=timezone.now() - timedelta(days=30)).count()
    average_login_age = 0
    login_users = total_users.exclude(last_login__isnull=True)
    if login_users.exists():
        age_sum = sum((timezone.now() - user.last_login).total_seconds() for user in login_users)
        average_login_age = age_sum / login_users.count() / 86400
    total_users = total_users.count()
    successful_deliveries = Order.objects.filter(status='delivered').count()
    successful_payments_raw = Order.objects.filter(
        Q(payment_status='completed') | Q(payment_confirmed=True)
    ).count()
    platform_earnings_raw = Order.objects.filter(
        Q(payment_status='completed') | Q(payment_confirmed=True)
    ).aggregate(earnings=Sum('total'))['earnings'] or Decimal('0')

    recent_conversations = BotConversation.objects.order_by('-created_at')[:10]
    top_keywords = LearnedKeyword.objects.order_by('-usage_count')[:10]
    token_summary = BotConversation.objects.aggregate(
        total_message_tokens=Sum('message_tokens'),
        total_response_tokens=Sum('response_tokens'),
        total_tokens=Sum('total_tokens')
    )
    average_tokens = 0
    if total_conversations:
        average_tokens = token_summary.get('total_tokens', 0) / total_conversations

    dashboard_mode = request.GET.get('mode') or 'editor'
    if dashboard_mode not in {'editor', 'cashier', 'stock', 'customers', 'cashiers', 'footer', 'header_ads'}:
        dashboard_mode = 'editor'

    stock_query = (request.GET.get('stock_q') or '').strip()
    stock_filter = request.GET.get('stock_filter') or 'all'
    products = Product.objects.select_related('category', 'brand').order_by('name')
    if stock_query:
        products = products.filter(
            Q(name__icontains=stock_query) |
            Q(category__name__icontains=stock_query) |
            Q(brand__name__icontains=stock_query)
        )
    if stock_filter == 'low':
        low_ids = [product.id for product in products if product.is_low_stock]
        products = Product.objects.filter(id__in=low_ids).select_related('category', 'brand').order_by('name')
    elif stock_filter == 'out':
        products = products.filter(stock=0)

    order_query = (request.GET.get('order_q') or '').strip()
    order_status = request.GET.get('order_status') or ''
    payment_status = request.GET.get('payment_status') or ''
    orders = Order.objects.prefetch_related('items__product').select_related('user').order_by('-created')
    if dashboard_mode == 'cashier' and not order_status:
        orders = orders.exclude(status__in=['cleared', 'cancelled'])
    if order_query:
        order_filters = (
            Q(first_name__icontains=order_query) |
            Q(last_name__icontains=order_query) |
            Q(phone__icontains=order_query) |
            Q(email__icontains=order_query) |
            Q(payment_reference__icontains=order_query)
        )
        if order_query.isdigit():
            order_filters |= Q(id=int(order_query))
        orders = orders.filter(order_filters)
    if order_status:
        orders = orders.filter(status=order_status)
    if payment_status:
        orders = orders.filter(payment_status=payment_status)

    recent_stock_adjustments = StockAdjustment.objects.select_related('product', 'user')[:12]
    categories = Category.objects.order_by('name')
    brands = Brand.objects.order_by('name')
    customer_query = (request.GET.get('customer_q') or '').strip()
    customers = ClientProfile.objects.select_related('user').order_by('-created_at')
    if customer_query:
        customers = customers.filter(
            Q(user__first_name__icontains=customer_query) |
            Q(user__last_name__icontains=customer_query) |
            Q(user__email__icontains=customer_query) |
            Q(phone_number__icontains=customer_query)
        )
    cashier_contacts = CashierContact.objects.order_by('name')
    payment_infos = PaymentInfo.objects.order_by('sort_order', 'title')
    newsletter_subscribers = NewsletterSubscriber.objects.order_by('-created_at')
    social_links = SocialLink.objects.order_by('sort_order', 'label')
    storefront_control = StorefrontControl.objects.first() or StorefrontControl.objects.create()
    subcategory_options = ['Tops', 'Bottoms', 'Shoes', 'Accessories']
    custom_subcategories = ProductSubcategory.objects.order_by('name')
    for subcategory in custom_subcategories:
        if subcategory.name.lower() not in {option.lower() for option in subcategory_options}:
            subcategory_options.append(subcategory.name)
    media_products_dir = os.path.join(settings.MEDIA_ROOT, 'products')
    uploaded_product_images = []
    if os.path.isdir(media_products_dir):
        for filename in sorted(os.listdir(media_products_dir))[:120]:
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                uploaded_product_images.append(f'products/{filename}')

    out_of_stock_count_raw = Product.objects.filter(stock=0).count()
    low_stock_count_raw = sum(1 for product in Product.objects.all() if product.is_low_stock)
    pending_order_count_raw = Order.objects.exclude(status__in=['delivered', 'cancelled', 'cleared', 'refunded']).count()
    analytic_resets = {
        reset.key: reset
        for reset in DashboardAnalyticReset.objects.filter(key__in=analytic_labels.keys())
    }

    def adjusted_analytic(key, raw_value):
        baseline = analytic_resets.get(key).baseline_value if analytic_resets.get(key) else Decimal('0')
        value = Decimal(raw_value) - baseline
        return value if value > 0 else Decimal('0')

    total_products = int(adjusted_analytic('products', total_products_raw))
    low_stock_count = int(adjusted_analytic('low_stock', low_stock_count_raw))
    out_of_stock_count = int(adjusted_analytic('out_of_stock', out_of_stock_count_raw))
    pending_order_count = int(adjusted_analytic('open_orders', pending_order_count_raw))
    successful_payments = int(adjusted_analytic('paid_orders', successful_payments_raw))
    platform_earnings = adjusted_analytic('revenue', platform_earnings_raw)

    return render(request, 'admin_dashboard.html', {
        'total_conversations': total_conversations,
        'total_learned_keywords': total_learned_keywords,
        'total_products': total_products,
        'total_categories': total_categories,
        'total_brands': total_brands,
        'total_users': total_users,
        'new_users': new_users,
        'old_users': old_users,
        'active_users_last_30_days': active_users_last_30_days,
        'average_login_age': average_login_age,
        'successful_deliveries': successful_deliveries,
        'successful_payments': successful_payments,
        'platform_earnings': platform_earnings,
        'recent_conversations': recent_conversations,
        'top_keywords': top_keywords,
        'token_summary': token_summary,
        'average_tokens': average_tokens,
        'products': products[:80],
        'orders': orders[:80],
        'categories': categories,
        'brands': brands,
        'customers': customers[:120],
        'customer_query': customer_query,
        'cashier_contacts': cashier_contacts,
        'payment_infos': payment_infos,
        'newsletter_subscribers': newsletter_subscribers[:200],
        'newsletter_subscriber_count': NewsletterSubscriber.objects.filter(active=True).count(),
        'social_links': social_links,
        'storefront_control': storefront_control,
        'subcategory_options': subcategory_options,
        'custom_subcategories': custom_subcategories,
        'uploaded_product_images': uploaded_product_images,
        'dashboard_mode': dashboard_mode,
        'recent_stock_adjustments': recent_stock_adjustments,
        'stock_query': stock_query,
        'stock_filter': stock_filter,
        'order_query': order_query,
        'order_status': order_status,
        'payment_status': payment_status,
        'order_status_choices': Order.STATUS_CHOICES,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'out_of_stock_count': out_of_stock_count,
        'low_stock_count': low_stock_count,
        'pending_order_count': pending_order_count,
        'analytic_resets': analytic_resets,
    })


@csrf_exempt
def shopping_bot(request):
    """PyTorch-powered shopping bot endpoint using intent classification."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        data = request.POST

    message = (data.get('message') or '').strip()
    product_name = (data.get('product_name') or '').strip()
    
    if not message:
        return JsonResponse({'response': 'Please ask me something!'})

    # Initialize PyTorch chatbot
    try:
        from .chatbot_model import get_chatbot
        chatbot = get_chatbot()
        response_text = chatbot.generate_response(message, product_name)
    except Exception as e:
        logger.error(f"PyTorch chatbot error: {e}")
        # Fallback to a simple response
        response_text = "I'm here to help. Try asking about products, shipping, or recommendations!"

    # Log conversation and session tracking
    session_id = request.session.get('bot_session_id')
    if not session_id:
        session_id = get_random_string(32)
        request.session['bot_session_id'] = session_id

    def count_tokens(text):
        return len(text.split()) if text else 0

    message_tokens = count_tokens(message)
    response_tokens = count_tokens(response_text)
    total_tokens = message_tokens + response_tokens

    # Try to find product context from message
    product = None
    if product_name:
        product = Product.objects.filter(name__iexact=product_name).first()

    try:
        BotConversation.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=session_id,
            product=product,
            message=message,
            response=response_text,
            message_tokens=message_tokens,
            response_tokens=response_tokens,
            total_tokens=total_tokens,
        )
    except Exception as e:
        logger.exception(f'Failed to save bot conversation: {e}')

    return JsonResponse({'response': response_text})

# def search_products(request):
#     query = request.GET.get('q', '')
#     if query:
#         products = Product.objects.filter(
#             Q(name__icontains=query) | 
#             Q(description__icontains=query) |
#             Q(category__name__icontains=query)
#         ).filter(available=True)
#     else:
#         products = Product.objects.none()
    
#     return render(request, 'search_results.html', {
#         'products': products,
#         'query': query
#     })

def _normalize_phone(phone):
    return normalize_account_phone(phone)


def _find_user_by_email_or_phone(identifier):
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    User = get_user_model()
    if '@' in identifier:
        return User.objects.filter(email__iexact=identifier).first()
    normalized = _normalize_phone(identifier)
    if normalized:
        return User.objects.filter(client_profile__phone_number__iexact=normalized).first()
    return None


def _send_password_reset_code(user):
    import random
    from users.models import PhoneOTP

    code = f"{random.randint(100000, 999999)}"
    expires = timezone.now() + timedelta(minutes=10)
    phone = ''
    try:
        phone = user.client_profile.phone_number
    except Exception:
        phone = ''

    PhoneOTP.objects.create(user=user, phone=phone or '', code=code, expires_at=expires)

    sent = False
    errors = []

    if phone:
        try:
            sms_client = SMSClient()
            result = sms_client.send_sms(phone, f"Your Normils password reset code is {code}")
            if isinstance(result, dict) and result.get('status') != 'success':
                raise Exception(result.get('message', 'SMS send failed'))
            sent = True
        except Exception as e:
            logger.exception('Failed to send password reset SMS for user %s: %s', user.id, e)
            errors.append('sms')

    if user.email:
        try:
            subject = 'Normils password reset code'
            message = f'Your Normils password reset code is {code}. Use this code to reset your password.'
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
            sent = True
        except Exception as e:
            logger.exception('Failed to send password reset email for user %s: %s', user.id, e)
            errors.append('email')

    return sent, errors


def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            phone = form.cleaned_data.get('phone', '')
            sent, message = send_phone_verification_code(user, phone)
            if not sent:
                user.delete()
                messages.error(request, message)
                return render(request, 'registration/signup.html', {'form': form})

            request.session['pending_user_id'] = user.id
            messages.success(request, message)
            return redirect('verify_otp')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'registration/signup.html', {'form': form})


def verify_otp(request):
    pending_user_id = request.session.get('pending_user_id')
    if not pending_user_id and request.user.is_authenticated and not request.user.is_verified:
        pending_user_id = request.user.id
        request.session['pending_user_id'] = pending_user_id
    if not pending_user_id:
        messages.error(request, 'No pending registration to verify.')
        return redirect('signup')

    from users.models import PhoneOTP
    from django.contrib.auth import login
    from django.shortcuts import redirect

    if request.method == 'POST':
        code = request.POST.get('code')
        try:
            otp = PhoneOTP.objects.filter(user_id=pending_user_id, used=False).order_by('-created_at').first()
            if not otp:
                messages.error(request, 'No OTP found. Please request a new code.')
                return redirect('signup')

            if otp.expires_at and otp.expires_at < timezone.now():
                messages.error(request, 'OTP has expired. Please signup again to request a new code.')
                return redirect('signup')

            if otp.code != code:
                messages.error(request, 'Invalid OTP code. Please try again.')
                return render(request, 'registration/verify_otp.html')

            # mark used and activate user
            otp.used = True
            otp.save()
            from users.models import User
            user = User.objects.get(id=pending_user_id)
            user.is_active = True
            user.is_verified = True
            user.save()
            # login
            backend_path = 'users.backends.EmailOrPhoneBackend'
            user.backend = backend_path
            login(request, user, backend=backend_path)
            del request.session['pending_user_id']
            return render(request, 'registration/verification_success.html', {'user': user})
        except Exception as e:
            logger.exception('OTP verification error: %s', e)
            messages.error(request, 'An error occurred while verifying OTP.')
            return render(request, 'registration/verify_otp.html')

    return render(request, 'registration/verify_otp.html')


def resend_otp(request):
    pending_user_id = request.session.get('pending_user_id')
    if not pending_user_id and request.user.is_authenticated and not request.user.is_verified:
        pending_user_id = request.user.id
        request.session['pending_user_id'] = pending_user_id
    is_json = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_ACCEPT', '').find('application/json') != -1
    if not pending_user_id:
        if is_json:
            return JsonResponse({'status': False, 'message': 'No pending registration to resend OTP for.'}, status=400)
        messages.error(request, 'No pending registration to resend OTP for.')
        return redirect('signup')

    from users.models import PhoneOTP, User
    user = User.objects.filter(id=pending_user_id).first()
    if not user:
        if is_json:
            return JsonResponse({'status': False, 'message': 'No pending registration found.'}, status=400)
        messages.error(request, 'No pending registration found.')
        return redirect('signup')

    # Normalize and validate stored phone before resending
    phone = ''
    try:
        phone = user.client_profile.phone_number
    except Exception:
        phone = ''

    if not phone:
        if is_json:
            return JsonResponse({'status': False, 'message': 'Cannot resend OTP because the phone number is missing.'}, status=400)
        messages.error(request, 'Cannot resend OTP because the phone number is missing.')
        return redirect('signup')

    normalized = ''.join(ch for ch in phone if ch.isdigit() or ch == '+')
    digits = ''.join(ch for ch in normalized if ch.isdigit())
    if len(digits) < 9:
        if is_json:
            return JsonResponse({'status': False, 'message': 'Cannot resend OTP: stored phone number is incomplete.'}, status=400)
        messages.error(request, 'Cannot resend OTP: stored phone number is incomplete.')
        return redirect('verify_otp')

    import random
    code = f"{random.randint(100000, 999999)}"
    expires = timezone.now() + timedelta(minutes=10)
    PhoneOTP.objects.create(user=user, phone=phone, code=code, expires_at=expires)

    try:
        sms_client = SMSClient()
        result = sms_client.send_sms(phone, f"Your Normils verification code is {code}")
        logger.warning('Resent OTP SMS result for user=%s phone=%s: %s', user.id, phone, result)
        if isinstance(result, dict) and result.get('status') != 'success':
            if is_json:
                return JsonResponse({'status': False, 'message': 'Verification code was generated, but could not be sent by SMS. Please check your phone number.'}, status=502)
            messages.warning(request, 'Verification code was generated, but could not be sent by SMS. Please check your phone number.')
        else:
            if is_json:
                return JsonResponse({'status': True, 'message': 'A new verification code has been sent to your phone.'})
            messages.success(request, 'A new verification code has been sent to your phone.')
    except Exception:
        logger.exception('Failed to resend OTP SMS for user %s', user.id)
        if is_json:
            return JsonResponse({'status': False, 'message': 'Failed to resend OTP SMS. Please try again later.'}, status=500)
        messages.error(request, 'Failed to resend OTP SMS. Please try again later.')

    return redirect('verify_otp')


def password_reset_request(request):
    if request.method == 'POST':
        identifier = (request.POST.get('identifier') or '').strip()
        if not identifier:
            messages.error(request, 'Please enter your email address or phone number to reset your password.')
            return render(request, 'registration/password_reset_request.html')

        user = _find_user_by_email_or_phone(identifier)
        if user:
            sent, errors = _send_password_reset_code(user)
            if sent:
                request.session['password_reset_user_id'] = user.id
                messages.success(request, 'A password reset code has been sent to your email and/or phone number.')
                return redirect('password_reset_verify')
            messages.error(request, 'We could not send a password reset code at this time. Please try again later.')
        else:
            messages.success(request, 'If that email or phone number is registered, a password reset code has been sent.')

    return render(request, 'registration/password_reset_request.html')


def password_reset_verify(request):
    pending_user_id = request.session.get('password_reset_user_id')
    if not pending_user_id:
        messages.error(request, 'Please enter your email address or phone number first.')
        return redirect('password_reset_request')

    if request.method == 'POST':
        code = request.POST.get('code')
        try:
            from users.models import PhoneOTP
            otp = PhoneOTP.objects.filter(user_id=pending_user_id, used=False).order_by('-created_at').first()
            if not otp:
                messages.error(request, 'No OTP found. Please request a new code.')
                return redirect('password_reset_request')

            if otp.expires_at and otp.expires_at < timezone.now():
                messages.error(request, 'Your password reset code has expired. Please request a new code.')
                return redirect('password_reset_request')

            if otp.code != code:
                messages.error(request, 'Invalid reset code. Please try again.')
                return render(request, 'registration/password_reset_verify.html')

            otp.used = True
            otp.save()
            request.session['password_reset_verified_user_id'] = pending_user_id
            del request.session['password_reset_user_id']
            messages.success(request, 'Code verified. You can now set a new password.')
            return redirect('password_reset_form')
        except Exception as e:
            logger.exception('Password reset OTP verification error: %s', e)
            messages.error(request, 'An error occurred while verifying the reset code.')
            return render(request, 'registration/password_reset_verify.html')

    return render(request, 'registration/password_reset_verify.html')


def password_reset_form(request):
    verified_user_id = request.session.get('password_reset_verified_user_id')
    if not verified_user_id:
        messages.error(request, 'Please verify a reset code before setting a new password.')
        return redirect('password_reset_request')

    User = get_user_model()
    user = User.objects.filter(id=verified_user_id).first()
    if not user:
        messages.error(request, 'We could not find your account. Please try again.')
        return redirect('password_reset_request')

    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            backend_path = 'users.backends.EmailOrPhoneBackend'
            user.backend = backend_path
            login(request, user, backend=backend_path)
            if 'password_reset_verified_user_id' in request.session:
                del request.session['password_reset_verified_user_id']
            messages.success(request, 'Your password has been reset successfully.')
            return redirect('home')
    else:
        form = SetPasswordForm(user)

    for field in form.fields.values():
        field.widget.attrs.update({
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
        })

    return render(request, 'registration/password_reset_form.html', {'form': form})


def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, available=True)
    variant_id = request.POST.get('variant_id')
    quantity = _parse_positive_int(request.POST.get('quantity'), 1)

    if product.stock <= 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect('product_detail', slug=product.slug)
    
    cart = get_or_create_cart(request)
    
    variant = None
    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
    
    cart_item = CartItem.objects.filter(cart=cart, product=product, variant=variant).first()
    existing_quantity = cart_item.quantity if cart_item else 0
    requested_quantity = existing_quantity + quantity
    if requested_quantity > product.stock:
        messages.error(request, f"Only {product.stock} of {product.name} available.")
        if existing_quantity:
            return redirect('cart')
        return redirect('product_detail', slug=product.slug)
    
    if cart_item:
        cart_item.quantity = requested_quantity
        cart_item.save()
    else:
        CartItem.objects.create(
            cart=cart,
            product=product,
            variant=variant,
            quantity=quantity
        )
    
    messages.success(request, f"{product.name} added to your cart.")
    return redirect('cart')

def update_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id)
    
    if request.user.is_authenticated:
        if cart_item.cart.user != request.user:
            messages.error(request, "You don't have permission to modify this cart.")
            return redirect('store:cart')
    else:
        session_id = request.session.get('cart_id')
        if not session_id or cart_item.cart.session_id != session_id:
            messages.error(request, "You don't have permission to modify this cart.")
            return redirect('store:cart')
    
    action = request.POST.get('action')
    
    if action == 'update':
        quantity = _parse_positive_int(request.POST.get('quantity'), 1)
        if quantity > 0:
            if quantity > cart_item.product.stock:
                quantity = cart_item.product.stock
                messages.warning(request, f"Quantity adjusted to available stock for {cart_item.product.name}.")
            if quantity <= 0:
                cart_item.delete()
                return redirect('cart')
            cart_item.quantity = quantity
            cart_item.save()
        else:
            cart_item.delete()
    elif action == 'remove':
        cart_item.delete()
    
    return redirect('cart')

def cart(request):
    cart = get_or_create_cart(request)
    return render(request, 'cart.html', {
        'cart': cart,
        'checkout_amounts': _checkout_amounts(cart.total, 'cash'),
    })


def _send_order_created_notifications(order_id):
    close_old_connections()
    try:
        order = Order.objects.prefetch_related('items__product').select_related('store').get(id=order_id)
        send_order_receipt_sms(order)
        send_admin_whatsapp_order_receipt(order)
        send_order_confirmation_email(order)
        _notify_cashiers_order_created(order)
    except Exception:
        logger.exception('Background order notification failed for Order ID %s', order_id)
    finally:
        close_old_connections()


def _queue_order_created_notifications(order):
    thread = threading.Thread(
        target=_send_order_created_notifications,
        args=(order.id,),
        name=f'order-notifications-{order.id}',
        daemon=True,
    )
    thread.start()


def _unique_checkout_username(first_name, phone, email=''):
    base_value = email.split('@')[0] if email else f"{first_name}-{phone}"
    base = re.sub(r'[^a-zA-Z0-9._+-]', '', base_value)[:24] or get_random_string(8)
    username = base
    while get_user_model().objects.filter(username=username).exists():
        username = f"{base[:24]}{get_random_string(6)}"
    return username


def _create_customer_account(request, first_name, last_name, email, phone, password, password2, address=''):
    if len(password) < 8:
        return None, 'Please use a password with at least 8 characters.'
    if password != password2:
        return None, 'Password and confirm password must match.'

    first_name = (first_name or 'Customer').strip()
    last_name = (last_name or '').strip()
    email = (email or '').strip().lower()
    phone = _normalize_phone(phone)
    UserModel = get_user_model()

    if not phone:
        return None, 'Please enter a valid phone number.'
    if email and UserModel.objects.filter(email__iexact=email).exists():
        return None, 'That email is already signed up. Please log in before checkout.'
    if ClientProfile.objects.filter(phone_number__iexact=phone).exists():
        return None, 'That phone number is already signed up. Please log in before checkout.'

    user = UserModel(
        username=_unique_checkout_username(first_name, phone, email),
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_client=True,
        is_verified=False,
        is_active=True,
    )
    user.set_password(password)
    user.save()
    login(request, user, backend='users.backends.EmailOrPhoneBackend')
    profile, _ = ClientProfile.objects.get_or_create(user=user)
    profile.phone_number = phone
    profile.address = address or ''
    profile.save(update_fields=['phone_number', 'address', 'updated_at'])
    sent, message = send_phone_verification_code(user, phone)
    if sent:
        request.session['pending_user_id'] = user.id
    else:
        logger.warning('Account %s created but OTP was not sent: %s', user.id, message)
    return user, None


def _create_checkout_customer(request, form):
    if request.user.is_authenticated:
        return request.user, None

    return _create_customer_account(
        request,
        form.cleaned_data['first_name'],
        form.cleaned_data.get('last_name', ''),
        form.cleaned_data.get('email', ''),
        form.cleaned_data['phone'],
        request.POST.get('checkout_password') or '',
        request.POST.get('checkout_password2') or '',
        form.cleaned_data.get('address', ''),
    )


def account_quick_create(request):
    if request.method != 'POST':
        return JsonResponse({'status': False, 'message': 'POST required'}, status=405)
    if request.user.is_authenticated:
        return JsonResponse({'status': True, 'message': 'You are already signed in.'})

    full_name = (request.POST.get('name') or '').strip()
    if not full_name:
        return JsonResponse({'status': False, 'message': 'Please enter your name.'}, status=400)
    names = full_name.split()
    first_name = names[0] if names else ''
    last_name = ' '.join(names[1:])
    user, error = _create_customer_account(
        request,
        first_name,
        last_name,
        request.POST.get('email') or '',
        request.POST.get('phone') or '',
        request.POST.get('password') or '',
        request.POST.get('password2') or '',
        '',
    )
    if error:
        return JsonResponse({'status': False, 'message': error}, status=400)
    profile = ClientProfile.objects.get(user=user)
    return JsonResponse({
        'status': True,
        'message': 'Account Created successful',
        'data': {
            'name': user.get_full_name() or user.username,
            'phone': profile.phone_number,
            'email': user.email,
            'verify_url': reverse('verify_otp'),
        },
    })


@login_required
def account_save_address(request):
    if request.method != 'POST':
        return JsonResponse({'status': False, 'message': 'POST required'}, status=405)

    city = (request.POST.get('city') or '').strip()
    area = (request.POST.get('area') or '').strip()
    if not city or not area:
        return JsonResponse({'status': False, 'message': 'Town or City and Area are required.'}, status=400)

    profile, _ = ClientProfile.objects.get_or_create(user=request.user)
    profile.address = f"{area}, {city}"
    profile.save(update_fields=['address', 'updated_at'])
    return JsonResponse({'status': True, 'message': 'Address saved.'})


def checkout(request):
    cart = get_or_create_cart(request)
    
    if not cart.items.exists():
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_ACCEPT', '').find('application/json') != -1:
            return JsonResponse({
                'status': False,
                'message': 'Your cart is empty.',
                'data': None
            }, status=400)
        else:
            messages.warning(request, "Your cart is empty.")
            return redirect('cart')
    
    if request.method == 'POST':
        logger.info(f"Checkout POST data: {request.POST}")
        is_chat_checkout = request.POST.get('checkout_mode') == 'chat'
        stock_issues = _cart_stock_issues(cart)
        if stock_issues:
            return JsonResponse({
                'status': False,
                'message': ' '.join(stock_issues),
                'data': None
            }, status=400)
        
        form = CheckoutForm(request.POST)
        if form.is_valid():
            if request.user.is_authenticated and not _normalize_phone(form.cleaned_data.get('phone', '')):
                return JsonResponse({
                    'status': False,
                    'message': 'Please add a valid phone number in Account Settings before checkout.',
                    'data': {'profile_url': reverse('profile')},
                }, status=400)
            checkout_user, customer_error = _create_checkout_customer(request, form)
            if customer_error:
                return JsonResponse({
                    'status': False,
                    'message': customer_error,
                    'data': None
                }, status=400)
            amounts = _checkout_amounts(cart.total, form.cleaned_data['payment_method'])
            subtotal = amounts['subtotal']
            shipping = amounts['shipping']
            tax = amounts['tax']
            total = amounts['total']
            
            # Determine the store for this order from the first cart item
            order_store = None
            first_cart_item = cart.items.first()
            if first_cart_item:
                order_store = first_cart_item.product.store
                if cart.items.exclude(product__store=order_store).exists():
                    logger.warning('Cart contains products from multiple stores. Using first item store=%s for order %s.', order_store, request.user.id)

            # Create the order
            order = Order.objects.create(
                user=checkout_user,
                store=order_store,
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                email=form.cleaned_data.get('email', ''),
                address=form.cleaned_data.get('address', ''),
                city=form.cleaned_data.get('city', ''),
                postal_code=form.cleaned_data.get('postal_code', ''),
                phone=_normalize_phone(form.cleaned_data['phone']),
                subtotal=subtotal,
                shipping=shipping,
                tax=tax,
                total=total,
                delivery_method=form.cleaned_data['delivery_method'],
                notes=form.cleaned_data.get('notes', ''),
                payment_method=form.cleaned_data['payment_method'],
                payment_status='processing' if form.cleaned_data['payment_method'] == 'mobile_money' else 'pending',
                status='payment_awaiting',
                payment_details={
                    'checkout': {
                        'base_tax': str(amounts['base_tax']),
                        'mobile_money_fee': str(amounts['mobile_money_fee']),
                        'tax_total': str(amounts['tax']),
                    }
                }
            )
            _remember_order_for_session(request, order)
            
            # Add order items
            for cart_item in cart.items.select_related('source_deal', 'product', 'variant').all():
                variant_info = ""
                if cart_item.variant:
                    variant_parts = []
                    if cart_item.variant.color:
                        variant_parts.append(cart_item.variant.color)
                    if cart_item.variant.size:
                        variant_parts.append(cart_item.variant.size)
                    variant_info = " / ".join(variant_parts)
                if cart_item.source_deal_id:
                    deal_terms = cart_item.source_deal.agreed_terms or cart_item.source_deal.customer_terms
                    variant_info = f"Deal #{cart_item.source_deal_id}"
                    if deal_terms:
                        variant_info = f"{variant_info}: {deal_terms[:80]}"
                
                item_price = cart_item.negotiated_price if cart_item.negotiated_price is not None else cart_item.product.price
                if cart_item.variant:
                    item_price += cart_item.variant.price_adjustment
                
                OrderItem.objects.create(
                    order=order,
                    product=cart_item.product,
                    variant_info=variant_info,
                    price=item_price,
                    quantity=cart_item.quantity
                )
                if cart_item.source_deal_id:
                    cart_item.source_deal.status = 'converted'
                    cart_item.source_deal.converted_order = order
                    cart_item.source_deal.save(update_fields=['status', 'converted_order', 'updated_at'])
            
            # Chat checkout should answer immediately once the order is stored.
            if not is_chat_checkout and form.cleaned_data['payment_method'] != 'cash':
                try:
                    if form.cleaned_data['payment_method'] == 'cash':
                        send_order_receipt_sms(order)
                    else:
                        send_order_sms(order)
                except Exception as sms_exc:
                    logger.exception('Immediate order SMS failed for Order ID %s', order.id)

                send_admin_whatsapp_order_receipt(order)
                _notify_cashiers_order_created(order)

            # Process payment based on selected method
            payment_method = form.cleaned_data['payment_method']
            
            if payment_method == 'mobile_money':
                try:
                    phone = form.cleaned_data['phone']
                    mobile_operator = request.POST.get('mobile_operator', 'airtel').lower()
                    if mobile_operator not in ['airtel', 'mtn']:
                        mobile_operator = 'airtel'  # Default to airtel if invalid
                    
                    logger.info(
                        "Payment request - Order ID: %s, Amount: %s, Phone: %s, Operator: %s, Mobile money fee: %s",
                        order.id,
                        total,
                        phone,
                        mobile_operator,
                        amounts['mobile_money_fee'],
                    )
                    
                    # Generate a unique reference
                    reference = f"ORDER-{order.id}-{uuid.uuid4().hex[:6]}"
                    
                    payment_response = process_lenco_payment(
                        amount=float(total),
                        phone_number=phone,
                        reference=reference,
                        operator=mobile_operator
                    )

                    logger.info(f"Payment response - Order ID: {order.id}, Response: {json.dumps(payment_response, indent=2)}")

                    if not payment_response.get('status', False):
                        error_message = payment_response.get('message', 'Payment processing failed')
                        logger.error(f"Payment error - Order ID: {order.id}, Error: {error_message}")
                        
                        order.payment_status = 'failed'
                        order.payment_details = {
                            **(order.payment_details or {}),
                            'lenco_response': payment_response,
                        }
                        order.save()
                        
                        return JsonResponse({
                            'status': False,
                            'message': error_message,
                            'data': None
                        }, status=400)

                    payment_data = payment_response.get('data', {})
                    order.payment_reference = payment_data.get('lencoReference') or payment_data.get('reference', '')
                    order.payment_details = {
                        **(order.payment_details or {}),
                        'lenco_response': payment_response,
                    }

                    payment_status = payment_data.get('status', 'pending')
                    order.payment_status = _order_payment_status(payment_status)
                    order.save()

                    logger.info(f"Order updated - ID: {order.id}, Status: {payment_status}, Reference: {order.payment_reference}")

                    json_response = None

                    if payment_status in ('pending', 'pay-offline'):
                        order.status = 'payment_awaiting'
                        order.save(update_fields=['status'])
                        json_response = {
                            'status': True,
                            'message': 'Please authorize the mobile money payment on your phone.',
                            'data': {
                                'order_id': order.id,
                                'payment_reference': order.payment_reference,
                                'status': payment_status
                            }
                        }
                    elif payment_status == 'successful':
                        _set_order_paid(order)
                        cart.items.all().delete()
                        send_order_confirmation_email(order)
                        json_response = {
                            'status': True,
                            'message': 'Order placed successfully! Your payment was successful.',
                            'data': {
                                'order_id': order.id
                            }
                        }
                    else:
                        reason = payment_data.get('reasonForFailure', 'Unknown error')
                        message = reason if reason else f"Payment status: {payment_status}"
                        
                        messages.error(request, message)
                        
                        json_response = {
                            'status': False,
                            'message': message,
                            'data': None
                        }

                    logger.info(f"JSON response to client - Order ID: {order.id}, Response: {json.dumps(json_response, indent=2)}")
                    return JsonResponse(json_response, status=400 if not json_response['status'] else 200)

                except Exception as e:
                    logger.error(f"Payment processing error - Order ID: {order.id}, Error: {str(e)}")
                    order.payment_status = 'failed'
                    order.save()
                    
                    error_response = {
                        'status': False,
                        'message': str(e),
                        'data': None
                    }
                    
                    logger.info(f"Error response to client - Order ID: {order.id}, Response: {json.dumps(error_response, indent=2)}")
                    messages.error(request, "An error occurred while processing your payment. Please try again.")
                    return JsonResponse(error_response, status=500)

            elif payment_method == 'cash':
                order.payment_status = 'pending'
                order.status = 'payment_awaiting'
                order.save(update_fields=['payment_status', 'status'])
                cart.items.all().delete()
                _notify_cashiers_order_created(order)
                cash_message = _message_payment_text(order)
                json_response = {
                    'status': True,
                    'message': cash_message,
                    'data': {
                        'order_id': order.id,
                        'total': str(order.total),
                        'total_display': _money_display(order.total),
                        'payment_status': order.payment_status,
                        'payment_infos': _payment_info_payload(),
                        'receipt_message': _payment_confirmed_receipt_message(order),
                    }
                }
                logger.info(f"Cash payment response - Order ID: {order.id}, Response: {json.dumps(json_response, indent=2)}")
                messages.success(request, "Your order has been placed. Please send payment and wait for cashier confirmation.")
                return JsonResponse(json_response)
        else:
            errors = {field: error[0] for field, error in form.errors.items()}
            error_response = {
                'status': False,
                'message': 'Form validation failed',
                'errors': errors,
                'data': None
            }
            logger.error(f"Form validation errors: {json.dumps(errors, indent=2)}")
            return JsonResponse(error_response, status=400)
    else:
        initial_data = {}
        if request.user.is_authenticated and request.user.first_name:
            initial_data['first_name'] = request.user.first_name
        if request.user.is_authenticated and request.user.last_name:
            initial_data['last_name'] = request.user.last_name
        if request.user.is_authenticated and request.user.email:
            initial_data['email'] = request.user.email
        
        form = CheckoutForm(initial=initial_data)
    
    cash_amounts = _checkout_amounts(cart.total, 'cash')
    mobile_money_amounts = _checkout_amounts(cart.total, 'mobile_money')

    return render(request, 'checkout.html', {
        'cart': cart,
        'form': form,
        'checkout_amounts': cash_amounts,
        'mobile_money_amounts': mobile_money_amounts,
        'payment_infos': _active_payment_infos(),
    })

def send_order_confirmation_email(order):
    if not order.email:
        logger.info('Order confirmation email skipped for order %s: no customer email.', order.id)
        return
    subject = f"Order Confirmation - #{order.id}"
    html_message = render_to_string('emails/order_confirmation.html', {'order': order})
    plain_message = strip_tags(html_message)
    from_email = settings.DEFAULT_FROM_EMAIL
    to_email = order.email
    
    send_mail(subject, plain_message, from_email, [to_email], html_message=html_message)

@login_required
@login_required
def submit_otp(request, order_id):
    """Handle OTP submission for mobile money payments"""
    if request.method != 'POST':
        error_response = {"status": False, "message": "Method not allowed", "data": None}
        logger.error(f"OTP submission error - Order ID: {order_id}, Error: Method not allowed")
        return JsonResponse(error_response, status=405)
    
    order = get_object_or_404(Order, id=order_id, user=request.user)
    
    # Get OTP from request
    try:
        data = json.loads(request.body)
        otp = data.get('otp')
        
        # Log the OTP submission request (mask the actual OTP for security)
        masked_otp = '*' * len(otp) if otp else None
        logger.info(f"OTP submission request - Order ID: {order_id}, OTP: {masked_otp}")
        
        if not otp:
            error_response = {"status": False, "message": "OTP is required", "data": None}
            logger.error(f"OTP submission error - Order ID: {order_id}, Error: OTP is required")
            return JsonResponse(error_response, status=400)
        
        # Get transaction reference from order
        transaction_reference = order.payment_reference
        
        if not transaction_reference:
            error_response = {"status": False, "message": "No payment reference found", "data": None}
            logger.error(f"OTP submission error - Order ID: {order_id}, Error: No payment reference found")
            return JsonResponse(error_response, status=400)
        
        # Submit OTP
        logger.info(f"Submitting OTP - Order ID: {order_id}, Reference: {transaction_reference}")
        
        otp_response = submit_lenco_otp(otp, transaction_reference)
        
        # Log the OTP submission response
        logger.info(f"OTP submission response - Order ID: {order_id}, Response: {json.dumps(otp_response, indent=2)}")
        
        if not otp_response.get('status', False):
            error_message = otp_response.get('message', 'OTP submission failed')
            
            order.payment_status = 'failed'
            order.payment_details = {
                **(order.payment_details or {}),
                'otp_response': otp_response
            }
            order.save()
            
            error_response = {
                "status": False,
                "message": error_message,
                "data": None
            }
            
            logger.error(f"OTP validation failed - Order ID: {order_id}, Error: {error_message}")
            
            return JsonResponse(error_response, status=400)
        
        # Update order status based on OTP response
        payment_data = otp_response.get('data', {})
        payment_status = payment_data.get('status', 'pending')
        
        order.payment_status = _order_payment_status(payment_status)
        order.payment_details = {
            **(order.payment_details or {}),
            'otp_response': otp_response
        }
        order.save()
        
        logger.info(f"Order updated after OTP - ID: {order_id}, Status: {payment_status}")
        
        json_response = None
        
        if payment_status == 'successful':
            # Clear the cart
            try:
                _set_order_paid(order)
            except ValueError as exc:
                return JsonResponse({"status": False, "message": str(exc), "data": None}, status=400)
            cart = get_or_create_cart(request)
            cart.items.all().delete()
            
            # Send order confirmation email
            send_order_confirmation_email(order)
            
            json_response = {
                "status": True,
                "message": "Payment successful",
                "data": {"order_id": order.id}
            }
            
            logger.info(f"Payment successful after OTP - Order ID: {order_id}")
        else:
            reason = payment_data.get('reasonForFailure', 'Payment failed')
            
            json_response = {
                "status": False,
                "message": reason,
                "data": None
            }
            
            logger.error(f"Payment failed after OTP - Order ID: {order_id}, Reason: {reason}")
        
        # Log the JSON response being sent to the client
        logger.info(f"JSON response to client after OTP - Order ID: {order_id}, Response: {json.dumps(json_response, indent=2)}")
        
        return JsonResponse(json_response, status=400 if not json_response['status'] else 200)
    
    except json.JSONDecodeError:
        error_message = "Invalid JSON in request body"
        logger.error(f"OTP submission error - Order ID: {order_id}, Error: {error_message}")
        return JsonResponse({"status": False, "message": error_message, "data": None}, status=400)
    
    except Exception as e:
        error_message = str(e)
        logger.error(f"OTP submission error - Order ID: {order_id}, Error: {error_message}")
        
        order.payment_status = 'failed'
        order.save()
        
        error_response = {
            "status": False,
            "message": error_message,
            "data": None
        }
        
        return JsonResponse(error_response, status=500)

def order_confirmation(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if not _can_access_order(request, order):
        return HttpResponseForbidden('You do not have access to this order.')
    return render(request, 'order_confirmation.html', {
        'order': order,
        'payment_infos': _active_payment_infos(),
        'receipt_message': _payment_confirmed_receipt_message(order),
    })


def start_lenco_payment(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if not _can_access_order(request, order):
        return JsonResponse({'status': False, 'message': 'Forbidden', 'data': None}, status=403)
    if request.method != 'POST':
        return JsonResponse({'status': False, 'message': 'POST required', 'data': None}, status=405)
    if order.payment_status == 'completed' or order.payment_confirmed:
        return JsonResponse({
            'status': True,
            'message': 'Payment Confirmed',
            'data': {
                'order_id': order.id,
                'payment_status': 'completed',
                'receipt_message': _payment_confirmed_receipt_message(order),
            },
        })

    operator = (request.POST.get('mobile_operator') or 'airtel').lower()
    if operator not in {'airtel', 'mtn'}:
        operator = 'airtel'

    billing_phone = order.phone
    if order.user_id and order.user_id == request.user.id:
        profile_phone = getattr(getattr(request.user, 'client_profile', None), 'phone_number', '')
        billing_phone = profile_phone or billing_phone
        if profile_phone and profile_phone != order.phone:
            order.phone = profile_phone
            order.save(update_fields=['phone'])

    reference = order.payment_reference
    if not reference or order.payment_status == 'failed':
        reference = f"ORDER-{order.id}-{uuid.uuid4().hex[:6]}"
    payment_response = process_lenco_payment(
        amount=float(order.total),
        phone_number=billing_phone,
        reference=reference,
        operator=operator,
    )

    if not payment_response.get('status', False):
        order.payment_method = 'mobile_money'
        order.payment_reference = reference
        order.payment_details = {
            **(order.payment_details or {}),
            'lenco_response': payment_response,
        }
        order.save(update_fields=['payment_method', 'payment_reference', 'payment_details'])
        return JsonResponse({
            'status': False,
            'message': payment_response.get('message', 'Lenco payment request failed.'),
            'data': None,
        }, status=400)

    payment_data = payment_response.get('data') or {}
    lenco_status = payment_data.get('status', 'pending')
    order.payment_method = 'mobile_money'
    order.payment_reference = payment_data.get('lencoReference') or payment_data.get('reference') or reference
    order.payment_status = _order_payment_status(lenco_status)
    if order.payment_status == 'completed':
        order.status = 'paid'
    else:
        order.status = 'payment_awaiting'
    order.payment_details = {
        **(order.payment_details or {}),
        'lenco_response': payment_response,
    }
    order.save(update_fields=['payment_method', 'payment_reference', 'payment_status', 'status', 'payment_details'])

    if order.payment_status == 'completed':
        try:
            _set_order_paid(order)
        except ValueError as exc:
            return JsonResponse({'status': False, 'message': str(exc), 'data': None}, status=400)
        try:
            send_order_confirmation_email(order)
        except Exception:
            logger.exception('Payment confirmation email failed for Order ID %s', order.id)
        return JsonResponse({
            'status': True,
            'message': 'Payment Confirmed',
            'data': {
                'order_id': order.id,
                'payment_status': 'completed',
                'payment_reference': order.payment_reference,
                'receipt_message': _payment_confirmed_receipt_message(order),
            },
        })

    return JsonResponse({
        'status': True,
        'message': 'Payment request sent. Please approve the Lenco prompt on your phone.',
        'data': {
            'order_id': order.id,
            'payment_status': order.payment_status,
            'lenco_status': lenco_status,
            'payment_reference': order.payment_reference,
        },
    })


@login_required
def order_history(request):
    orders = Order.objects.filter(user=request.user)
    return render(request, 'order_history.html', {'orders': orders})

def verify_payment(request, order_id):
    """Endpoint to verify payment status"""
    order = get_object_or_404(Order, id=order_id)
    if not _can_access_order(request, order):
        return JsonResponse({'status': False, 'message': 'Forbidden', 'data': None}, status=403)
    
    # Check payment status with Lenco API
    payment_status = _get_order_collection_status(order)
    
    if payment_status.get('status', False):
        lenco_status = payment_status['data'].get('status', 'pending')
        was_paid = order.payment_status == 'completed' or order.payment_confirmed
        order.payment_status = _order_payment_status(lenco_status)
        if order.payment_status == 'completed':
            order.status = 'paid'
        order.save()

        if order.payment_status == 'completed' and not was_paid:
            try:
                _deduct_stock_for_order(order)
            except ValueError as exc:
                return JsonResponse({
                    'status': False,
                    'message': str(exc),
                    'data': None
                }, status=400)
            try:
                send_order_confirmation_email(order)
            except Exception:
                logger.exception('Payment confirmation email failed for Order ID %s', order.id)
            order.notify_payment_confirmed()
        
        return JsonResponse({
            'status': True,
            'order_id': order.id,
            'payment_status': order.payment_status,
            'lenco_status': lenco_status,
            'payment_reference': order.payment_reference,
            'data': {
                'order_id': order.id,
                'receipt_message': _payment_confirmed_receipt_message(order) if order.payment_status == 'completed' else '',
            }
        })
    else:
        return JsonResponse({
            'status': False,
            'message': payment_status.get('message', 'Failed to verify payment'),
            'data': None
        }, status=400)

@login_required
def add_on_delivery(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order.notify_shipped()
    messages.success(request, 'Order marked as shipped and notifications sent.')
    return redirect('order_confirmation', order_id=order.id)

@login_required
def received_parcel(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order.notify_delivered()
    messages.success(request, 'Order marked as delivered and notifications sent.')
    return redirect('order_confirmation', order_id=order.id)

def confirm_payment(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if not _can_access_order(request, order):
        return HttpResponseForbidden('You do not have access to this order.')

    if order.payment_method == 'cash':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_ACCEPT', '').find('application/json') != -1:
            is_confirmed = order.payment_confirmed or order.payment_status == 'completed'
            return JsonResponse({
                'status': True,
                'order_id': order.id,
                'payment_status': 'completed' if is_confirmed else order.payment_status,
                'order_status': order.status,
                'message': 'Payment Confirmed' if is_confirmed else 'Waiting confirmation.',
                'data': {
                    'order_id': order.id,
                    'receipt_message': _payment_confirmed_receipt_message(order) if is_confirmed else '',
                },
            })
        messages.info(request, 'Waiting for cashier payment confirmation.')
        return redirect('order_confirmation', order_id=order.id)

    if request.method == 'POST':
        pin = request.POST.get('pin')

        # Process the payment using the Lenco API
        payment_response = process_lenco_payment(
            amount=order.total,
            phone_number=order.phone,
            reference=order.transaction_id,
            operator="airtel"  # or any other operator
        )

        # Update the order status based on the payment response
        if payment_response['status'] == 'success':
            order.payment_status = 'completed'
            order.status = 'paid'
            order.save()
            try:
                _deduct_stock_for_order(order)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('order_confirmation', order_id=order.id)
            order.notify_payment_confirmed()
            messages.success(request, 'Payment successful! Your order is being processed.')
        elif payment_response['status'] == 'insufficient_balance':
            order.payment_status = 'failed'
            order.status = 'cancelled'
            messages.error(request, 'Payment failed: Insufficient balance.')
        else:
            order.payment_status = 'failed'
            order.status = 'cancelled'
            messages.error(request, 'Payment failed. Please try again.')

        order.save()

        return redirect('order_confirmation', order_id=order.id)

    return render(request, 'confirm_payment.html', {'order': order})

def buy_now(request, slug):
    product = get_object_or_404(Product, slug=slug)
    # Add logic to handle the "Buy Now" action
    return redirect('checkout')  # Redirect to the checkout page
