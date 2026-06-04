import json
from pathlib import Path
from django.conf import settings
from .models import Product, BotConversation

MODEL_PATH = Path(settings.BASE_DIR) / 'store' / 'recommender.json'
FEATURE_FIELDS = ['category', 'brand', 'season', 'fabric', 'color', 'cost_range']
UNKNOWN_VALUE = 'unknown'


def _normalize_feature(value):
    if not value:
        return UNKNOWN_VALUE
    normalized = str(value).strip().lower()
    return normalized if normalized else UNKNOWN_VALUE


def _product_features(product):
    return {
        'category': _normalize_feature(product.category.slug if product.category else None),
        'brand': _normalize_feature(product.brand.slug if product.brand else None),
        'season': _normalize_feature(product.season),
        'fabric': _normalize_feature(product.fabric),
        'color': _normalize_feature(product.color),
        'cost_range': _normalize_feature(product.cost_range),
    }


def _build_context_features(category=None, brand=None, season=None, fabric=None, color=None, cost_range=None):
    return {
        'category': _normalize_feature(category),
        'brand': _normalize_feature(brand),
        'season': _normalize_feature(season),
        'fabric': _normalize_feature(fabric),
        'color': _normalize_feature(color),
        'cost_range': _normalize_feature(cost_range),
    }


def _load_recommender():
    if not MODEL_PATH.exists():
        return None
    try:
        with open(MODEL_PATH, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def _save_recommender(model):
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, 'w', encoding='utf-8') as fh:
        json.dump(model, fh)
    return MODEL_PATH


def train_recommender():
    conversations = BotConversation.objects.filter(product__isnull=False).select_related('product', 'product__category', 'product__brand')
    products = Product.objects.filter(available=True).select_related('category', 'brand')
    if not products.exists():
        return None

    feature_weights = {}
    for convo in conversations:
        product = convo.product
        if not product:
            continue
        product_features = _product_features(product)
        convo_features = _build_context_features(
            category=product.category.slug if product.category else None,
            brand=product.brand.slug if product.brand else None,
            season=convo.season or product.season,
            fabric=convo.fabric or product.fabric,
            color=convo.color or product.color,
            cost_range=convo.cost_range or product.cost_range,
        )

        for field, value in convo_features.items():
            key = f'{field}|{_normalize_feature(value)}'
            feature_weights[key] = feature_weights.get(key, 0) + 2

        for field, value in product_features.items():
            key = f'{field}|{value}'
            feature_weights[key] = feature_weights.get(key, 0) + 1

    product_features_map = {
        str(product.id): _product_features(product)
        for product in products
    }

    model = {
        'feature_weights': feature_weights,
        'product_features': product_features_map,
    }
    return _save_recommender(model)


def recommend_products_from_context(category=None, brand=None, season=None, fabric=None, color=None, cost_range=None, exclude_product=None, limit=6):
    model = _load_recommender()
    if model is None:
        train_recommender()
        model = _load_recommender()
    if model is None:
        products = Product.objects.filter(available=True)
        if exclude_product:
            products = products.exclude(id=exclude_product.id)
        return list(products.order_by('-created')[:limit])

    context = _build_context_features(category, brand, season, fabric, color, cost_range)
    scored = []

    for product_id, features in model['product_features'].items():
        if exclude_product and str(exclude_product.id) == product_id:
            continue

        score = 0
        for field, target_value in context.items():
            if target_value == UNKNOWN_VALUE:
                continue
            product_value = features.get(field, UNKNOWN_VALUE)
            score += model['feature_weights'].get(f'{field}|{target_value}', 0)
            if product_value == target_value:
                score += 1

        if score > 0:
            scored.append((int(product_id), score))

    if not scored:
        products = Product.objects.filter(available=True)
        if exclude_product:
            products = products.exclude(id=exclude_product.id)
        return list(products.order_by('-created')[:limit])

    scored.sort(key=lambda item: (-item[1], item[0]))
    ordered_ids = [product_id for product_id, _ in scored[:limit]]
    products = list(Product.objects.filter(id__in=ordered_ids))
    id_order = {pid: index for index, pid in enumerate(ordered_ids)}
    products.sort(key=lambda p: id_order.get(p.id, len(ordered_ids)))
    return products
