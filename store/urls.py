from django.urls import path
from . import views

# app_name = 'store'

urlpatterns = [
    
    #User related urls
    path('', views.home, name='home'),
    path('signup/', views.signup, name='signup'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('verify-otp/resend/', views.resend_otp, name='resend_otp'),
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('password-reset/verify/', views.password_reset_verify, name='password_reset_verify'),
    path('password-reset/new/', views.password_reset_form, name='password_reset_form'),
    path('subscribe/', views.subscribe_newsletter, name='subscribe_newsletter'),
    path('search/', views.search_products, name='search_products'),
    
    # Products related urls
    path('category/<slug:slug>/', views.category_detail, name='category_detail'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('product_detail/<slug:slug>/', views.product_detail, name='product_detail'),
    path('shopping-bot/', views.shopping_bot, name='shopping_bot'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('wishlist/add/', views.add_to_wishlist, name='add_to_wishlist'),
    path('wishlist/remove/', views.remove_from_wishlist, name='remove_from_wishlist'),
    path('account/quick-create/', views.account_quick_create, name='account_quick_create'),
    path('account/save-address/', views.account_save_address, name='account_save_address'),
    path('contact-us/', views.contact_us, name='contact_us'),
    path('shipping-policy/', views.shipping_policy, name='shipping_policy'),
    path('returns-refunds/', views.returns_refunds, name='returns_refunds'),
    
    # Purchase related urls
    # path('buy-now/<slug:slug>/', views.buy_now, name='buy_now'),
    path('cart/', views.cart, name='cart'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('update-cart-item/<int:item_id>/', views.update_cart_item, name='update_cart_item'),
    path('checkout/', views.checkout, name='checkout'),
    path('verify-payment/<int:order_id>/', views.verify_payment, name='verify_payment'),
    
    # Order related urls
    path('order/<int:order_id>/submit-otp/', views.submit_otp, name='submit_otp'),
    path('order/<int:order_id>/confirmation/', views.order_confirmation, name='order_confirmation'),
    path('order/<int:order_id>/start-lenco-payment/', views.start_lenco_payment, name='start_lenco_payment'),
    path('order/<int:order_id>/add-on-delivery/', views.add_on_delivery, name='add_on_delivery'),
    path('order/<int:order_id>/received-parcel/', views.received_parcel, name='received_parcel'),
    path('order/<int:order_id>/confirm-payment/', views.confirm_payment, name='confirm_payment'),
    path('order-history/', views.order_history, name='order_history'),
]
