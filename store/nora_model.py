"""Nora retrieval model using sentence-transformers embeddings.

This module loads a SentenceTransformer model once at import time and caches
product embeddings for cosine-similarity retrieval.
"""

import os
from pathlib import Path

import numpy as np
from django.conf import settings
from .models import Product
from .chatbot_model import get_chatbot

EMBEDDING_FILE = Path(__file__).resolve().parent / 'nora_product_embeddings.npz'

_product_embeddings = None
_product_ids = None


def _product_text(product: Product) -> str:
    parts = [product.name or '']
    if product.category:
        parts.append(product.category.name)
    if product.brand:
        parts.append(product.brand.name)
    if product.description:
        parts.append(product.description)
    return ' | '.join([p.strip() for p in parts if p.strip()])


def _build_product_embeddings():
    chatbot = get_chatbot()
    products = list(Product.objects.filter(available=True).select_related('category', 'brand'))
    if not products:
        return np.empty((0, 0), dtype=np.float32), np.array([], dtype=np.int32)

    texts = [_product_text(product) for product in products]
    # Use existing chatbot embedding function (returns numpy array)
    embeddings = np.stack([chatbot.get_embedding(t) for t in texts]).astype(np.float32)
    product_ids = np.array([product.id for product in products], dtype=np.int32)
    EMBEDDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(EMBEDDING_FILE, embeddings=embeddings, product_ids=product_ids)
    return embeddings, product_ids


def _load_product_embeddings():
    global _product_embeddings, _product_ids
    if _product_embeddings is not None and _product_ids is not None:
        return _product_embeddings, _product_ids

    if EMBEDDING_FILE.exists():
        try:
            data = np.load(EMBEDDING_FILE)
            _product_embeddings = data['embeddings']
            _product_ids = data['product_ids']
            return _product_embeddings, _product_ids
        except Exception:
            pass

    _product_embeddings, _product_ids = _build_product_embeddings()
    return _product_embeddings, _product_ids


def recommend_products_for_message(message: str, product_name: str = '', limit: int = 4, exclude_product=None):
    """Return the nearest product matches for a user message."""
    if not message:
        return []

    embeddings, product_ids = _load_product_embeddings()
    if embeddings.size == 0:
        return []

    query_text = f"{message.strip()} {product_name.strip()}".strip()
    if not query_text:
        return []

    model = _get_model()
    query_embedding = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]
    scores = embeddings @ query_embedding

    valid_indices = np.argsort(-scores)
    selected_ids = []
    for idx in valid_indices:
        pid = int(product_ids[idx])
        if exclude_product is not None and pid == exclude_product.id:
            continue
        selected_ids.append(pid)
        if len(selected_ids) >= limit:
            break

    if not selected_ids:
        return []

    products = list(Product.objects.filter(id__in=selected_ids).select_related('category', 'brand'))
    order = {pid: i for i, pid in enumerate(selected_ids)}
    products.sort(key=lambda p: order.get(p.id, len(order)))
    return products


def refresh_product_embeddings():
    """Force rebuild the cached product embeddings file."""
    global _product_embeddings, _product_ids
    _product_embeddings, _product_ids = _build_product_embeddings()
    return EMBEDDING_FILE
