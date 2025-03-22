from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from django.utils.crypto import get_random_string
from decimal import Decimal
import uuid
import json
from decimal import Decimal
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .models import Category, Product, ProductVariant, Cart, CartItem, Order, OrderItem
from .forms import CustomUserCreationForm, CheckoutForm
from .payment import process_lenco_payment, logger

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

def home(request):
    categories = Category.objects.all()
    products = Product.objects.all()

    # Get filter parameters from the request
    price_filter = request.GET.get('price')
    availability_filter = request.GET.get('availability')

    # Apply price filter
    if price_filter:
        products = products.filter(price__lte=float(price_filter))

    # Apply availability filter
    if availability_filter:
        if availability_filter == 'in_stock':
            products = products.filter(stock__gt=0)
        elif availability_filter == 'out_of_stock':
            products = products.filter(stock=0)

    return render(request, 'index.html', {
        'categories': categories,
        'products': products,
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
    return render(request, 'product_details.html', {
        'product': product,
        'variants': variants
    })

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
            login(request, user)
            messages.success(request, "Account created successfully!")
            return redirect('home')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'registration/signup.html', {'form': form})

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
            
            # Create the order
            order = Order.objects.create(
                user=request.user,
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                email=form.cleaned_data['email'],
                address=form.cleaned_data['address'],
                city=form.cleaned_data['city'],
                postal_code=form.cleaned_data['postal_code'],
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
                        # Notify the user to enter their mobile money PIN
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
                        # Notify the user to authorize the payment on their phone
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
                        
                        json_response = {
                            'status': True,
                            'message': 'Payment successful',
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
                    'message': 'Order placed successfully',
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
    from_email = 'noreply@example.com'
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