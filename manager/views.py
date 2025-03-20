from django.shortcuts import render, get_object_or_404
from .models import Store

def store_dashboard(request, store_slug):
    store = get_object_or_404(Store, slug=store_slug)
    orders = store.orders.all()
    products = store.products.all()

    context = {
        'store': store,
        'orders': orders,
        'products': products,
    }
    return render(request, 'store_dashboard.html', context)