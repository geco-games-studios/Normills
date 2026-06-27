from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from manager.models import Store
from users.models import StoreOwnerProfile
from .payment import (
    _format_zambian_phone,
    _lenco_authorization_header,
    best_lenco_data,
    normalize_lenco_response,
    process_lenco_payment,
)
from .models import Category, Order, OrderItem, Product


class LencoPaymentHelperTests(SimpleTestCase):
    def test_best_lenco_data_prefers_final_status(self):
        response = {
            'status': True,
            'data': [
                {'status': 'pending', 'reference': 'pending-ref'},
                {'status': 'successful', 'reference': 'paid-ref'},
            ],
        }

        self.assertEqual(best_lenco_data(response)['reference'], 'paid-ref')

    def test_normalize_lenco_response_collapses_data_list_to_best_item(self):
        response = {
            'status': True,
            'data': [
                {'status': 'pending', 'reference': 'pending-ref'},
                {'status': 'failed', 'reference': 'failed-ref'},
            ],
        }

        normalized = normalize_lenco_response(response)

        self.assertEqual(normalized['data']['reference'], 'failed-ref')

    @override_settings(LENCO_API_KEY='secret-token')
    def test_lenco_authorization_header_adds_bearer_prefix(self):
        self.assertEqual(_lenco_authorization_header(), 'Bearer secret-token')

    @override_settings(LENCO_API_KEY='Bearer existing-token')
    def test_lenco_authorization_header_keeps_existing_bearer_prefix(self):
        self.assertEqual(_lenco_authorization_header(), 'Bearer existing-token')

    def test_format_zambian_phone_normalizes_local_numbers(self):
        self.assertEqual(_format_zambian_phone('0977 123 456'), '260977123456')
        self.assertEqual(_format_zambian_phone('977123456'), '260977123456')

    @override_settings(LENCO_API_KEY='')
    def test_process_lenco_payment_fails_cleanly_when_api_key_missing(self):
        response = process_lenco_payment('25.00', '0977123456', 'test-ref')

        self.assertFalse(response['status'])
        self.assertIn('not configured', response['message'])


class MerchantDashboardTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(username='customer', password='password')
        self.merchant_user = User.objects.create_user(
            username='merchant',
            password='password',
            role=User.Role.MERCHANT,
            is_store_owner=True,
        )
        self.other_merchant_user = User.objects.create_user(
            username='other-merchant',
            password='password',
            role=User.Role.MERCHANT,
            is_store_owner=True,
        )
        self.owner_profile = self.merchant_user.store_owner_profile
        self.owner_profile.store_name = 'Merchant Store'
        self.owner_profile.phone_number = '260977123456'
        self.owner_profile.address = 'Mazabuka'
        self.owner_profile.save()
        self.other_owner_profile = self.other_merchant_user.store_owner_profile
        self.other_owner_profile.store_name = 'Other Store'
        self.other_owner_profile.phone_number = '260966123456'
        self.other_owner_profile.address = 'Mazabuka'
        self.other_owner_profile.save()
        self.store = Store.objects.create(
            name='Merchant Store',
            slug='merchant-store',
            owner=self.owner_profile,
        )
        self.other_store = Store.objects.create(
            name='Other Store',
            slug='other-store',
            owner=self.other_owner_profile,
        )
        self.category = Category.objects.create(name='Phones', slug='phones')
        self.product = Product.objects.create(
            name='Merchant Phone',
            slug='merchant-phone',
            category=self.category,
            store=self.store,
            price=Decimal('2500.00'),
            image='products/merchant-phone.jpg',
            stock=2,
            low_stock_threshold=3,
        )
        Product.objects.create(
            name='Other Phone',
            slug='other-phone',
            category=self.category,
            store=self.other_store,
            price=Decimal('3000.00'),
            image='products/other-phone.jpg',
            stock=10,
            low_stock_threshold=3,
        )
        self.order = Order.objects.create(
            user=self.customer,
            first_name='Customer',
            last_name='One',
            email='customer@example.com',
            address='Mazabuka',
            city='Mazabuka',
            postal_code='10101',
            phone='260977000000',
            status='paid',
            subtotal=Decimal('2500.00'),
            shipping=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('2500.00'),
            payment_method='mobile_money',
            payment_status='completed',
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            price=Decimal('2500.00'),
            quantity=1,
        )

    def test_customer_cannot_access_merchant_dashboard(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('merchant_dashboard'))

        self.assertEqual(response.status_code, 403)

    def test_merchant_can_access_own_dashboard_summary(self):
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['store_count'], 1)
        self.assertEqual(response.context['product_count'], 1)
        self.assertEqual(response.context['order_count'], 1)
        self.assertEqual(response.context['low_stock_count'], 1)
        self.assertEqual(response.context['total_revenue'], Decimal('2500'))
        self.assertContains(response, 'Merchant Phone')
        self.assertNotContains(response, 'Other Phone')

    def _uploaded_image(self):
        return SimpleUploadedFile('product.jpg', b'product-image-bytes', content_type='image/jpeg')

    def test_customer_cannot_access_product_create_form(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('merchant_product_create'))

        self.assertEqual(response.status_code, 403)

    def test_merchant_can_open_product_create_form(self):
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_product_create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add product')

    def test_merchant_can_publish_product_to_own_store(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_create'), {
            'store': self.store.id,
            'image': self._uploaded_image(),
            'name': 'Fresh Jacket',
            'price': '650.00',
            'category': self.category.id,
            'brand': '',
            'stock': '4',
            'description': 'Warm jacket',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        product = Product.objects.get(slug='fresh-jacket')
        self.assertEqual(product.store, self.store)
        self.assertEqual(product.price, Decimal('650.00'))
        self.assertEqual(product.stock, 4)
        self.assertTrue(product.available)

    def test_merchant_cannot_publish_product_to_another_merchants_store(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_create'), {
            'store': self.other_store.id,
            'image': self._uploaded_image(),
            'name': 'Wrong Store Product',
            'price': '100.00',
            'category': self.category.id,
            'brand': '',
            'stock': '1',
            'description': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(name='Wrong Store Product').exists())
