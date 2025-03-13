from .views import get_or_create_cart

def cart_processor(request):
    """Add cart information to all templates"""
    cart = get_or_create_cart(request)
    return {'cart': cart}
