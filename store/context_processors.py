from .views import get_or_create_cart
from .models import StorefrontControl, WishlistItem

def cart_processor(request):
    """Add cart and wishlist information to all templates."""
    cart = get_or_create_cart(request)
    if request.user.is_authenticated:
        wishlist_ids = list(
            WishlistItem.objects.filter(user=request.user).values_list('product_id', flat=True)
        )
    else:
        wishlist_ids = [int(pid) for pid in request.session.get('wishlist', []) if str(pid).isdigit()]

    return {
        'cart': cart,
        'wishlist_count': len(wishlist_ids),
        'wishlist_ids': [str(pid) for pid in wishlist_ids],
        'storefront_control': StorefrontControl.objects.first(),
    }
