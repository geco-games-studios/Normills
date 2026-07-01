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
    path('product/<slug:slug>/paygo/', views.paygo_apply, name='paygo_apply'),
    path('product/<slug:slug>/deal/', views.deal_start, name='deal_start'),
    path('paygo/', views.paygo_applications, name='paygo_applications'),
    path('paygo/<int:application_id>/', views.paygo_detail, name='paygo_detail'),
    path('deals/', views.deal_list, name='deal_list'),
    path('deals/<int:deal_id>/', views.deal_detail, name='deal_detail'),
    path('deals/<int:deal_id>/checkout/', views.deal_convert_to_checkout, name='deal_convert_to_checkout'),
    path('support/', views.support_tickets, name='support_tickets'),
    path('support/new/', views.support_ticket_create, name='support_ticket_create'),
    path('support/<int:ticket_id>/', views.support_ticket_detail, name='support_ticket_detail'),
    path('support/<int:ticket_id>/update/', views.support_ticket_update, name='support_ticket_update'),
    path('support/queue/', views.support_ticket_queue, name='support_ticket_queue'),
    path('shopping-bot/', views.shopping_bot, name='shopping_bot'),
    path('merchant/', views.merchant_dashboard, name='merchant_dashboard'),
    path('merchant/orders/', views.merchant_orders, name='merchant_orders'),
    path('merchant/payouts/', views.merchant_payouts, name='merchant_payouts'),
    path('merchant/deals/', views.merchant_deals, name='merchant_deals'),
    path('merchant/deals/<int:deal_id>/', views.merchant_deal_detail, name='merchant_deal_detail'),
    path('merchant/orders/<int:order_id>/', views.merchant_order_detail, name='merchant_order_detail'),
    path('merchant/orders/<int:order_id>/update/', views.merchant_order_update, name='merchant_order_update'),
    path('merchant/products/new/', views.merchant_product_create, name='merchant_product_create'),
    path('merchant/products/<int:product_id>/edit/', views.merchant_product_edit, name='merchant_product_edit'),
    path('merchant/products/<int:product_id>/duplicate/', views.merchant_product_duplicate, name='merchant_product_duplicate'),
    path('merchant/products/<int:product_id>/ads/generate/', views.merchant_product_generate_ad, name='merchant_product_generate_ad'),
    path('merchant/products/<int:product_id>/inventory/', views.merchant_product_inventory_update, name='merchant_product_inventory_update'),
    path('delivery/orders/', views.delivery_orders, name='delivery_orders'),
    path('delivery/orders/<int:order_id>/update/', views.delivery_order_update, name='delivery_order_update'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('finance/payouts/', views.finance_payouts, name='finance_payouts'),
    path('finance/payouts/batches/<int:batch_id>/', views.finance_payout_batch_detail, name='finance_payout_batch_detail'),
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
