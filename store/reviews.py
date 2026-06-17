"""
Product Reviews & Ratings System
Provides customer social proof — one of the strongest conversion tools.
"""

import logging
from django.db import models
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericRelation
from django.db.models import Avg, Count

from store.models import Product
from users.models import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class Review(models.Model):
    """A customer review + rating for a product."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='reviews'
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='product_reviews'
    )
    rating = models.PositiveSmallIntegerField(
        help_text='Rating out of 5 stars (1-5)'
    )
    title = models.CharField(max_length=200, blank=True)
    comment = models.TextField(blank=True)
    verified_purchase = models.BooleanField(
        default=False,
        help_text='True if the reviewer has purchased this product'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['product', 'user']  # one review per user per product
        verbose_name = 'Review'
        verbose_name_plural = 'Reviews'

    def __str__(self):
        return f'{self.user.username} — {self.product.name} ({self.rating}★)'

    def save(self, *args, **kwargs):
        # Clamp rating
        if self.rating < 1:
            self.rating = 1
        elif self.rating > 5:
            self.rating = 5
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Helpers  (used in views / templates)
# ---------------------------------------------------------------------------
def get_product_review_stats(product):
    """Return aggregate stats for a product: average rating & count."""
    stats = Review.objects.filter(product=product).aggregate(
        avg_rating=Avg('rating'),
        total_reviews=Count('id'),
    )
    stats['avg_rating'] = round(stats['avg_rating'] or 0, 1)
    stats['total_reviews'] = stats['total_reviews'] or 0
    return stats


def has_user_reviewed_product(user, product):
    if not user.is_authenticated:
        return False
    return Review.objects.filter(product=product, user=user).exists()