from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, get_user_model
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, Min, Max, Sum
from django.utils.crypto import get_random_string
from decimal import Decimal
import re
import uuid
import json
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .models import Category, Product, ProductVariant, Cart, CartItem, Order, OrderItem, Brand, BotConversation, LearnedKeyword
from .ml import recommend_products_from_context
from .forms import CustomUserCreationForm, CheckoutForm
from store.sms_client import SMSClient
from django.utils import timezone
from datetime import timedelta
from .payment import process_lenco_payment, logger
from .sms_service import send_order_sms, send_order_receipt_sms

from django.contrib import messages
import logging

logger = logging.getLogger(__name__)

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


def home(request):
    categories = Category.objects.all()
    products = Product.objects.all()
    brands = Brand.objects.all()

    # Get filter parameters from the request
    price_filter = request.GET.get('price')
    availability_filter = request.GET.get('availability')
    brand_filters = request.GET.getlist('brand')

    # Apply price filter
    if price_filter:
        products = products.filter(price__lte=float(price_filter))

    # Apply availability filter
    if availability_filter:
        if availability_filter == 'in_stock':
            products = products.filter(stock__gt=0)
        elif availability_filter == 'out_of_stock':
            products = products.filter(stock=0)

    # Apply brand filter (supports multiple selections)
    if brand_filters:
        products = products.filter(brand__slug__in=brand_filters)

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

    return render(request, 'index.html', {
        'categories': categories,
        'products': products,
        'brands': brands,
        'personalized_products': personalized_products,
        'recently_viewed_products': recently_viewed_products,
    })
    
    
def search_products(request):
    query = request.GET.get('q')
    if query:
        products = Product.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    else:
        products = Product.objects.all()
    return render(request, 'search_results.html', {'products': products})

def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = category.products.filter(available=True)
    return render(request, 'category_detail.html', {
        'category': category,
        'products': products
    })

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, available=True)
    variants = product.variants.all()

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

    return render(request, 'product_details.html', {
        'product': product,
        'variants': variants,
        'recommended_products': recommended_products,
        'product_url': product_url,
    })


@login_required
def admin_dashboard(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden('Superuser access only.')

    total_conversations = BotConversation.objects.count()
    total_learned_keywords = LearnedKeyword.objects.count()
    total_products = Product.objects.count()
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
    successful_payments = Order.objects.filter(
        Q(payment_status='completed') | Q(payment_confirmed=True)
    ).count()
    platform_earnings = Order.objects.filter(
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
    })


@csrf_exempt
def shopping_bot(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        data = request.POST

    message = (data.get('message') or '').strip()
    product_name = (data.get('product_name') or '').strip()

    def normalize_message_text(text):
        return ' '.join(''.join(ch if ch.isalnum() or ch.isspace() else ' ' for ch in text.lower()).split())

    def normalize_search_terms(search_text):
        stopwords = {
            'what', 'do', 'you', 'have', 'for', 'the', 'a', 'an', 'and', 'or', 'to', 'from', 'with', 'on', 'in', 'of',
            'me', 'show', 'looking', 'find', 'need', 'want', 'show', 'this', 'that', 'it', 'is', 'are', 'my', 'your',
            'best', 'here', 'there', 'these', 'those'
        }
        tokens = [token for token in re.findall(r'\b[a-z]{2,}\b', search_text)]
        terms = []
        for token in tokens:
            if token in stopwords:
                continue
            terms.append(token)
            if token == 'babies':
                terms.append('baby')
            if token == 'kids':
                terms.extend(['kid', 'children'])
            if token == 'children':
                terms.extend(['child', 'kids'])
            if token == 'women':
                terms.extend(['woman', 'female'])
            if token == 'men':
                terms.extend(['man', 'male'])
            if token.endswith('ies'):
                terms.append(token[:-3] + 'y')
            elif token.endswith('s') and len(token) > 3:
                terms.append(token[:-1])
        return list(dict.fromkeys(terms))

    def apply_learned_keyword_mapping(search_terms, category_ids, brand_ids, product):
        if not search_terms:
            return category_ids, brand_ids, product

        learned = LearnedKeyword.objects.filter(normalized_term__in=search_terms)
        for keyword in learned:
            if keyword.category_id:
                category_ids.add(keyword.category_id)
            if keyword.brand_id:
                brand_ids.add(keyword.brand_id)
            if not product and keyword.product_id:
                product = keyword.product
        return category_ids, brand_ids, product

    def learn_new_terms(search_terms, category_ids, brand_ids, product):
        if not search_terms:
            return
        for term in search_terms:
            keyword, created = LearnedKeyword.objects.get_or_create(
                normalized_term=term,
                defaults={'term': term}
            )
            if not created:
                keyword.usage_count = keyword.usage_count + 1 if keyword.usage_count is not None else 1
            if category_ids and keyword.category_id is None:
                keyword.category_id = next(iter(category_ids))
            if brand_ids and keyword.brand_id is None:
                keyword.brand_id = next(iter(brand_ids))
            if product and keyword.product_id is None:
                keyword.product = product
            keyword.save()

    def generate_bot_response(message_text, product_name=None):
        normalized = message_text.lower()
        normalized_search = normalize_message_text(message_text)
        if not normalized_search:
            return 'Hi there! Ask me about products, sharing, orders, or personalization.'

        def parse_price_range():
            price_min = None
            price_max = None
            found_numbers = re.findall(r'\d+(?:\.\d+)?', normalized_search)
            numeric = [Decimal(num) for num in found_numbers]
            if 'between' in normalized or ('from' in normalized and 'to' in normalized):
                if len(numeric) >= 2:
                    price_min, price_max = numeric[0], numeric[1]
            elif any(keyword in normalized for keyword in ['under', 'below', 'less than', 'max', 'up to']):
                if numeric:
                    price_max = numeric[0]
            elif any(keyword in normalized for keyword in ['over', 'above', 'more than', 'at least', 'minimum']):
                if numeric:
                    price_min = numeric[0]
            elif numeric:
                price_max = numeric[0]

            if any(keyword in normalized for keyword in ['cheap', 'budget', 'affordable', 'low cost']):
                price_max = price_max or Decimal('200')
            if any(keyword in normalized for keyword in ['premium', 'luxury', 'high end', 'expensive']):
                price_min = price_min or Decimal('1000')

            return price_min, price_max

        def parse_profile():
            age = None
            weight = None
            height_inches = None
            gender = None
            if re.search(r'\b(female|girl|daughter|woman|lady|women)\b', normalized):
                gender = 'female'
            elif re.search(r'\b(male|boy|son|man|gentleman|men)\b', normalized):
                gender = 'male'

            age_match = re.search(r'\b(\d{1,2})\s*(?:years?|yrs?|y/o|yo)\b', normalized)
            if age_match:
                age = int(age_match.group(1))
            else:
                age_match = re.search(r'\b(\d{1,2})\s*(?:months|mos?)\b', normalized)
                if age_match:
                    age = 0

            weight_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:kg|kilograms?)\b', normalized)
            if weight_match:
                try:
                    weight = Decimal(weight_match.group(1))
                except Exception:
                    weight = None

            height_match = re.search(r"\b(\d+)\s*(?:'|feet|ft)\s*(\d+)?\s*(?:\"|inches|in)?\b", normalized)
            if height_match:
                feet = int(height_match.group(1))
                inches = int(height_match.group(2) or 0)
                height_inches = feet * 12 + inches
            else:
                height_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b', normalized)
                if height_match:
                    try:
                        cm = Decimal(height_match.group(1))
                        height_inches = int((cm / Decimal('2.54')).quantize(Decimal('1')))
                    except Exception:
                        height_inches = None

            return age, weight, height_inches, gender

        def normalize_search_terms(search_text):
            stopwords = {
                'what', 'do', 'you', 'have', 'for', 'the', 'a', 'an', 'and', 'or', 'to', 'from', 'with', 'on', 'in', 'of',
                'me', 'show', 'looking', 'find', 'need', 'want', 'show', 'this', 'that', 'it', 'is', 'are', 'my', 'your',
                'best', 'here', 'there', 'these', 'those'
            }
            tokens = [token for token in re.findall(r'\b[a-z]{2,}\b', search_text)]
            terms = []
            for token in tokens:
                if token in stopwords:
                    continue
                terms.append(token)
                if token == 'babies':
                    terms.append('baby')
                if token == 'kids':
                    terms.extend(['kid', 'children'])
                if token == 'children':
                    terms.extend(['child', 'kids'])
                if token == 'women':
                    terms.extend(['woman', 'female'])
                if token == 'men':
                    terms.extend(['man', 'male'])
                if token.endswith('ies'):
                    terms.append(token[:-3] + 'y')
                elif token.endswith('s') and len(token) > 3:
                    terms.append(token[:-1])
            return list(dict.fromkeys(terms))

        def apply_learned_keyword_mapping(search_terms, category_ids, brand_ids, product):
            if not search_terms:
                return category_ids, brand_ids, product

            learned = LearnedKeyword.objects.filter(normalized_term__in=search_terms)
            for keyword in learned:
                if keyword.category_id:
                    category_ids.add(keyword.category_id)
                if keyword.brand_id:
                    brand_ids.add(keyword.brand_id)
                if not product and keyword.product_id:
                    product = keyword.product
            return category_ids, brand_ids, product

        def learn_new_terms(search_terms, category_ids, brand_ids, product):
            if not search_terms:
                return
            for term in search_terms:
                keyword, created = LearnedKeyword.objects.get_or_create(
                    normalized_term=term,
                    defaults={'term': term}
                )
                if not created:
                    keyword.usage_count = keyword.usage_count + 1 if keyword.usage_count is not None else 1
                if category_ids and keyword.category_id is None:
                    keyword.category_id = next(iter(category_ids))
                if brand_ids and keyword.brand_id is None:
                    keyword.brand_id = next(iter(brand_ids))
                if product and keyword.product_id is None:
                    keyword.product = product
                keyword.save()

        def build_profile_terms(age=None, gender=None):
            terms = []
            if age is not None:
                if age <= 3:
                    terms += ['baby', 'toddler', 'infant']
                elif age <= 8:
                    terms += ['kids', 'children', 'girls', 'boys']
                elif age <= 12:
                    terms += ['kids', 'children', 'youth']
                elif age <= 17:
                    terms += ['teen', 'youth', 'kids']
                else:
                    terms += ['adult', 'men', 'women', 'women', 'men']

            if gender == 'female':
                terms += ['girl', 'woman', 'women', 'female']
            elif gender == 'male':
                terms += ['boy', 'man', 'men', 'male']

            return list(dict.fromkeys(terms))

        def cost_range_keywords():
            if any(keyword in normalized for keyword in ['budget', 'cheap', 'affordable', 'economical']):
                return ['budget', 'value']
            if any(keyword in normalized for keyword in ['standard', 'midrange', 'mid-range']):
                return ['standard']
            if any(keyword in normalized for keyword in ['premium', 'luxury', 'high end', 'expensive']):
                return ['premium', 'luxury']
            return []

        def build_product_query(price_min=None, price_max=None, cost_ranges=None, profile_terms=None, search_terms=None, category_ids=None, brand_ids=None, product=None):
            q = Q(available=True)
            if search_terms:
                search_q = Q()
                for term in search_terms:
                    search_q |= (
                        Q(name__icontains=term) |
                        Q(description__icontains=term) |
                        Q(category__name__icontains=term) |
                        Q(brand__name__icontains=term)
                    )
                q &= search_q
            elif product_name:
                q &= Q(name__icontains=product_name) | Q(description__icontains=product_name)

            if profile_terms:
                profile_q = Q()
                for term in profile_terms:
                    profile_q |= (
                        Q(name__icontains=term) |
                        Q(description__icontains=term) |
                        Q(category__name__icontains=term) |
                        Q(brand__name__icontains=term)
                    )
                q &= profile_q

            if category_ids:
                q &= Q(category_id__in=category_ids)
            if brand_ids:
                q &= Q(brand_id__in=brand_ids)
            if product is not None:
                q &= Q(id=product.id)

            if price_min is not None:
                q &= Q(price__gte=price_min)
            if price_max is not None:
                q &= Q(price__lte=price_max)
            if cost_ranges:
                q &= Q(cost_range__in=cost_ranges)
            return q

        def summarize_price(products):
            if not products.exists():
                return ''
            price_info = products.aggregate(min_price=Min('price'), max_price=Max('price'))
            min_price = price_info.get('min_price')
            max_price = price_info.get('max_price')
            if min_price is None or max_price is None:
                return ''
            if min_price == max_price:
                return f' Prices start at {min_price}.'
            return f' Prices range from {min_price} to {max_price}.'

        if 'recommend' in normalized or 'suggest' in normalized:
            if product_name:
                return f"If you like {product_name}, try the product recommendations shown below. I also look at your recent views and order history to personalize suggestions."
            return 'I can recommend products based on your recently viewed items and order history. Browse a product page or category to get personalized suggestions.'

        if 'stock' in normalized or 'available' in normalized or 'inventory' in normalized:
            return 'Stock levels are shown on the product page. If an item is available, you can add it to your cart immediately.'

        if 'share' in normalized or 'friend' in normalized or 'whatsapp' in normalized or 'facebook' in normalized:
            return 'Use the share buttons on the product page to send a direct link, or copy the product link and paste it into chat or email.'

        if 'order' in normalized or 'delivery' in normalized or 'shipping' in normalized:
            return 'Orders are usually dispatched within 1-2 business days. You can track your order in My Orders once the purchase is placed.'

        if 'personalize' in normalized or 'personalization' in normalized or 'recommendation' in normalized:
            return 'I personalize recommendations using the products you view and the categories or brands you like. The more you browse, the better the suggestions become.'

        if 'hello' in normalized or 'hi' in normalized or 'hey' in normalized:
            return 'Hello! I can help you find products, answer shipping questions, or help you share items with friends.'

        categories = Category.objects.filter(name__icontains=normalized_search)
        brands = Brand.objects.filter(name__icontains=normalized_search)
        price_min, price_max = parse_price_range()
        cost_ranges = cost_range_keywords()
        profile_age, profile_weight, profile_height, profile_gender = parse_profile()
        profile_terms = build_profile_terms(profile_age, profile_gender)
        search_terms = normalize_search_terms(normalized_search)

        category_ids = set(categories.values_list('id', flat=True))
        brand_ids = set(brands.values_list('id', flat=True))
        product_attachment = None
        category_ids, brand_ids, product_attachment = apply_learned_keyword_mapping(
            search_terms, category_ids, brand_ids, product_attachment
        )

        query = build_product_query(
            price_min=price_min,
            price_max=price_max,
            cost_ranges=cost_ranges,
            profile_terms=profile_terms,
            search_terms=search_terms,
            category_ids=category_ids,
            brand_ids=brand_ids,
            product=product_attachment,
        )
        search_matches = Product.objects.filter(query).distinct()[:6]

        if profile_age is not None or profile_weight is not None or profile_height is not None or profile_gender is not None:
            if search_matches.exists():
                names = ', '.join([p.name for p in search_matches[:3]])
                age_text = f'{profile_age}-year-old ' if profile_age is not None and profile_age > 0 else ''
                gender_text = 'girl' if profile_gender == 'female' and (profile_age is None or profile_age <= 17) else \
                    'boy' if profile_gender == 'male' and (profile_age is None or profile_age <= 17) else \
                    'woman' if profile_gender == 'female' else \
                    'man' if profile_gender == 'male' else 'person'
                weight_text = f' around {profile_weight}kg' if profile_weight is not None else ''
                height_text = f' and about {profile_height} inches tall' if profile_height is not None else ''
                return (
                    f'For a {age_text}{gender_text}{weight_text}{height_text}, I found suitable products like {names}. '
                    'These recommendations are pulled from all categories in the store, including clothing, accessories, and footwear.'
                )

        if search_matches.exists():
            names = ', '.join([p.name for p in search_matches[:3]])
            context_parts = []
            if categories.exists():
                context_parts.append(f"category '{categories.first().name}'")
            if brands.exists():
                context_parts.append(f"brand '{brands.first().name}'")
            if price_min is not None or price_max is not None:
                low = f'from {price_min}' if price_min is not None else ''
                high = f'up to {price_max}' if price_max is not None else ''
                context_parts.append(f'price range {low} {high}'.strip())
            if cost_ranges:
                context_parts.append(f'cost level {", ".join(cost_ranges)}')
            context = ' and '.join(context_parts) if context_parts else 'your query'
            price_summary = summarize_price(search_matches)
            return f'I found products for {context}: {names}.{price_summary} Use search or category listings to see more.'

        if any(word in normalized_search for word in ['what do you have', 'show me', 'find', 'looking for', 'do you have', 'need', 'want', 'clothes', 'dress', 'shoes', 'bag']):
            generic_matches = Product.objects.filter(
                Q(name__icontains=normalized_search) |
                Q(description__icontains=normalized_search) |
                Q(category__name__icontains=normalized_search) |
                Q(brand__name__icontains=normalized_search)
            ).distinct()[:6]
            if generic_matches.exists():
                names = ', '.join([p.name for p in generic_matches[:3]])
                price_summary = summarize_price(generic_matches)
                return f'I found products matching that request: {names}.{price_summary} Try viewing the product list for more.'

        return 'I’m here to help. Try asking about stock, shipping, sharing, or product recommendations.'

    response_text = generate_bot_response(message, product_name)

    session_id = request.session.get('bot_session_id')
    if not session_id:
        session_id = get_random_string(32)
        request.session['bot_session_id'] = session_id

    def count_tokens(text):
        if not text:
            return 0
        return len(text.split())

    message_tokens = count_tokens(message)
    response_tokens = count_tokens(response_text)
    total_tokens = message_tokens + response_tokens

    bot_category_ids, bot_brand_ids, season, fabric, color, cost_range = extract_bot_interest(message)
    product = None
    if product_name:
        product = Product.objects.filter(name__iexact=product_name).first()
        if product:
            if product.category_id:
                bot_category_ids.add(product.category_id)
            if product.brand_id:
                bot_brand_ids.add(product.brand_id)
            if not season and product.season:
                season = product.season
            if not fabric and product.fabric:
                fabric = product.fabric
            if not color and product.color:
                color = product.color
            if not cost_range and product.cost_range:
                cost_range = product.cost_range

    try:
        BotConversation.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=session_id,
            product=product,
            message=message,
            response=response_text,
            category_ids=list(bot_category_ids) if bot_category_ids else None,
            brand_ids=list(bot_brand_ids) if bot_brand_ids else None,
            season=season,
            fabric=fabric,
            color=color,
            cost_range=cost_range,
            message_tokens=message_tokens,
            response_tokens=response_tokens,
            total_tokens=total_tokens,
        )
    except Exception:
        logger.exception('Failed to save bot conversation')

    try:
        learn_new_terms(normalize_search_terms(normalize_message_text(message)), bot_category_ids, bot_brand_ids, product)
    except Exception:
        logger.exception('Failed to save learned keyword mappings')

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

def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # create OTP and send via SMS
            from users.models import PhoneOTP, ClientProfile
            import random
            code = f"{random.randint(100000, 999999)}"
            # Use the cleaned, normalized phone from the validated form
            phone = form.cleaned_data.get('phone', '')

            expires = timezone.now() + timedelta(minutes=10)
            PhoneOTP.objects.create(user=user, phone=phone, code=code, expires_at=expires)

            try:
                sms_client = SMSClient()
                result = sms_client.send_sms(phone, f"Your Normils verification code is {code}")
                logger.warning('OTP SMS send result for user=%s phone=%s: %s', user.id, phone, result)
                logger.debug('Generated OTP for user=%s: %s (phone=%s)', user.id, code, phone)
                if isinstance(result, dict) and result.get('status') != 'success':
                    logger.warning('OTP SMS likely not sent for user=%s phone=%s: %s', user.id, phone, result)
            except Exception:
                logger.exception('Failed to send OTP SMS for user %s', user.id)

            request.session['pending_user_id'] = user.id
            return redirect('verify_otp')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'registration/signup.html', {'form': form})


def verify_otp(request):
    pending_user_id = request.session.get('pending_user_id')
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
            user.save()
            # login
            login(request, user)
            del request.session['pending_user_id']
            messages.success(request, 'Your phone has been verified and account activated.')
            return redirect('home')
        except Exception as e:
            logger.exception('OTP verification error: %s', e)
            messages.error(request, 'An error occurred while verifying OTP.')
            return render(request, 'registration/verify_otp.html')

    return render(request, 'registration/verify_otp.html')


def resend_otp(request):
    pending_user_id = request.session.get('pending_user_id')
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


def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, available=True)
    variant_id = request.POST.get('variant_id')
    quantity = int(request.POST.get('quantity', 1))
    
    cart = get_or_create_cart(request)
    
    variant = None
    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
    
    cart_item = CartItem.objects.filter(cart=cart, product=product, variant=variant).first()
    
    if cart_item:
        cart_item.quantity += quantity
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
        quantity = int(request.POST.get('quantity', 1))
        if quantity > 0:
            cart_item.quantity = quantity
            cart_item.save()
        else:
            cart_item.delete()
    elif action == 'remove':
        cart_item.delete()
    
    return redirect('cart')

def cart(request):
    cart = get_or_create_cart(request)
    return render(request, 'cart.html', {'cart': cart})

@login_required
@login_required
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
        
        form = CheckoutForm(request.POST)
        if form.is_valid():
            subtotal = cart.total
            shipping = Decimal('5.00')
            tax = subtotal * Decimal('0.02')
            total = subtotal + shipping + tax
            
            # Determine the store for this order from the first cart item
            order_store = None
            first_cart_item = cart.items.first()
            if first_cart_item:
                order_store = first_cart_item.product.store
                if cart.items.exclude(product__store=order_store).exists():
                    logger.warning('Cart contains products from multiple stores. Using first item store=%s for order %s.', order_store, request.user.id)

            # Create the order
            order = Order.objects.create(
                user=request.user,
                store=order_store,
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                email=form.cleaned_data.get('email', ''),
                address=form.cleaned_data.get('address', ''),
                city=form.cleaned_data.get('city', ''),
                postal_code=form.cleaned_data.get('postal_code', ''),
                phone=form.cleaned_data['phone'],
                subtotal=subtotal,
                shipping=shipping,
                tax=tax,
                total=total,
                payment_method=form.cleaned_data['payment_method'],
                payment_status='pending'
            )
            
            # Add order items
            for cart_item in cart.items.all():
                variant_info = ""
                if cart_item.variant:
                    variant_parts = []
                    if cart_item.variant.color:
                        variant_parts.append(cart_item.variant.color)
                    if cart_item.variant.size:
                        variant_parts.append(cart_item.variant.size)
                    variant_info = " / ".join(variant_parts)
                
                item_price = cart_item.product.price
                if cart_item.variant:
                    item_price += cart_item.variant.price_adjustment
                
                OrderItem.objects.create(
                    order=order,
                    product=cart_item.product,
                    variant_info=variant_info,
                    price=item_price,
                    quantity=cart_item.quantity
                )
            
            # Send SMS immediately when the order is created
            try:
                if form.cleaned_data['payment_method'] == 'cash':
                    send_order_receipt_sms(order)
                else:
                    send_order_sms(order)
            except Exception as sms_exc:
                logger.exception('Immediate order SMS failed for Order ID %s', order.id)

            # Process payment based on selected method
            payment_method = form.cleaned_data['payment_method']
            
            if payment_method == 'mobile_money':
                try:
                    phone = form.cleaned_data['phone']
                    mobile_operator = request.POST.get('mobile_operator', 'airtel').lower()
                    if mobile_operator not in ['airtel', 'mtn']:
                        mobile_operator = 'airtel'  # Default to airtel if invalid
                    
                    logger.info(f"Payment request - Order ID: {order.id}, Amount: {total}, Phone: {phone}, Operator: {mobile_operator}")
                    
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
                        order.payment_details = payment_response
                        order.save()
                        
                        return JsonResponse({
                            'status': False,
                            'message': error_message,
                            'data': None
                        }, status=400)

                    payment_data = payment_response.get('data', {})
                    order.payment_reference = payment_data.get('lencoReference') or payment_data.get('reference', '')
                    order.payment_details = payment_response

                    payment_status = payment_data.get('status', 'pending')
                    order.payment_status = payment_status
                    order.save()

                    logger.info(f"Order updated - ID: {order.id}, Status: {payment_status}, Reference: {order.payment_reference}")

                    json_response = None

                    if payment_status == 'otp-required':
                        json_response = {
                            'status': True,
                            'message': 'Please enter your mobile money PIN to authorize the payment.',
                            'data': {
                                'order_id': order.id,
                                'payment_reference': order.payment_reference,
                                'status': 'otp-required'
                            }
                        }
                    elif payment_status == 'pay-offline':
                        json_response = {
                            'status': True,
                            'message': 'Please authorize the payment on your mobile money app.',
                            'data': {
                                'order_id': order.id,
                                'payment_reference': order.payment_reference,
                                'status': 'pay-offline'
                            }
                        }
                    elif payment_status == 'successful':
                        cart.items.all().delete()
                        send_order_confirmation_email(order)
                        order.notify_payment_confirmed()
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
                order.save()
                cart.items.all().delete()
                send_order_confirmation_email(order)
                json_response = {
                    'status': True,
                    'message': 'Order placed successfully! You will pay on delivery.',
                    'data': {
                        'order_id': order.id
                    }
                }
                logger.info(f"Cash payment response - Order ID: {order.id}, Response: {json.dumps(json_response, indent=2)}")
                messages.success(request, "Your order has been placed successfully! You'll pay on delivery.")
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
        if request.user.first_name:
            initial_data['first_name'] = request.user.first_name
        if request.user.last_name:
            initial_data['last_name'] = request.user.last_name
        if request.user.email:
            initial_data['email'] = request.user.email
        
        form = CheckoutForm(initial=initial_data)
    
    return render(request, 'checkout.html', {
        'cart': cart,
        'form': form
    })

def send_order_confirmation_email(order):
    subject = f"Order Confirmation - #{order.id}"
    html_message = render_to_string('emails/order_confirmation.html', {'order': order})
    plain_message = strip_tags(html_message)
    from_email = 'hello@gecogames.com'  # Must match your SMTP user and DEFAULT_FROM_EMAIL
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
                **order.payment_details,
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
        
        order.payment_status = payment_status
        order.payment_details = {
            **order.payment_details,
            'otp_response': otp_response
        }
        order.save()
        
        logger.info(f"Order updated after OTP - ID: {order_id}, Status: {payment_status}")
        
        json_response = None
        
        if payment_status == 'successful':
            # Clear the cart
            cart = get_or_create_cart(request)
            cart.items.all().delete()
            
            # Send order confirmation email
            send_order_confirmation_email(order)
            order.notify_payment_confirmed()
            
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

@login_required
def order_confirmation(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'order_confirmation.html', {'order': order})

@login_required
def order_history(request):
    orders = Order.objects.filter(user=request.user)
    return render(request, 'order_history.html', {'orders': orders})

@login_required
@login_required
def verify_payment(request, order_id):
    """Endpoint to verify payment status"""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    
    # Check payment status with Lenco API
    payment_status = get_collection_status(order.payment_reference)
    
    if payment_status.get('status', False):
        order.payment_status = payment_status['data'].get('status', 'pending')
        order.save()
        
        return JsonResponse({
            'order_id': order.id,
            'payment_status': order.payment_status,
            'payment_reference': order.payment_reference
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
    return redirect('order_detail', order_id=order.id)

@login_required
def received_parcel(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order.notify_delivered()
    messages.success(request, 'Order marked as delivered and notifications sent.')
    return redirect('order_detail', order_id=order.id)

@login_required
def confirm_payment(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)

    # For cash on delivery, skip the timer and go directly to confirmation
    if order.payment_method == 'cash':
        # Mark payment as completed for cash on delivery
        order.payment_status = 'completed'
        order.status = 'processing'
        order.save()

        messages.success(request, 'Order placed successfully! Your order is being processed.')
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
            order.status = 'processing'
            order.save()
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