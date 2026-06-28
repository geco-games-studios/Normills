from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from manager.models import Store
from users.models import StoreOwnerProfile
from .payment import (
    _format_zambian_phone,
    _lenco_authorization_header,
    best_lenco_data,
    normalize_lenco_response,
    process_lenco_payment,
)
from .models import Category, Order, OrderItem, Product, ProductImage


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
        self.assertContains(response, f'#{self.order.id}')

    def _uploaded_image(self, name='product.jpg', size=(320, 240), color=(40, 80, 120)):
        image = Image.new('RGB', size, color=color)
        buffer = BytesIO()
        image.save(buffer, format='JPEG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')

    def _large_uploaded_image(self):
        return self._uploaded_image('large-product.jpg', size=(2400, 1800), color=(80, 120, 40))

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
            'available': 'on',
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

    def test_product_create_rejects_non_image_upload(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_create'), {
            'store': self.store.id,
            'image': SimpleUploadedFile('not-image.txt', b'not an image', content_type='text/plain'),
            'name': 'Bad Upload',
            'price': '100.00',
            'category': self.category.id,
            'brand': '',
            'stock': '1',
            'available': 'on',
            'description': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(name='Bad Upload').exists())
        self.assertContains(response, 'Upload a valid image')

    def test_product_create_resizes_large_image_upload(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_create'), {
            'store': self.store.id,
            'image': self._large_uploaded_image(),
            'name': 'Large Image Product',
            'price': '150.00',
            'category': self.category.id,
            'brand': '',
            'stock': '3',
            'available': 'on',
            'description': '',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        product = Product.objects.get(slug='large-image-product')
        with product.image.open('rb') as image_file:
            saved_image = Image.open(image_file)
            self.assertLessEqual(max(saved_image.size), 1600)

    def test_merchant_can_publish_product_with_gallery_images(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_create'), {
            'store': self.store.id,
            'image': self._uploaded_image('cover.jpg'),
            'supporting_images': [
                self._uploaded_image('angle-one.jpg', color=(120, 80, 40)),
                self._uploaded_image('angle-two.jpg', color=(40, 120, 80)),
            ],
            'name': 'Gallery Product',
            'price': '350.00',
            'category': self.category.id,
            'brand': '',
            'stock': '5',
            'available': 'on',
            'description': '',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        product = Product.objects.get(slug='gallery-product')
        self.assertEqual(product.supporting_images.count(), 2)
        with product.supporting_images.first().image.open('rb') as image_file:
            saved_image = Image.open(image_file)
            self.assertLessEqual(max(saved_image.size), 1600)

    def test_merchant_can_edit_own_product(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_edit', args=[self.product.id]), {
            'store': self.store.id,
            'name': 'Updated Merchant Phone',
            'price': '2400.00',
            'category': self.category.id,
            'brand': '',
            'stock': '7',
            'available': 'on',
            'description': 'Updated description',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Updated Merchant Phone')
        self.assertEqual(self.product.price, Decimal('2400.00'))
        self.assertEqual(self.product.stock, 7)
        self.assertTrue(self.product.available)

    def test_merchant_can_update_gallery_images(self):
        existing_image = ProductImage.objects.create(
            product=self.product,
            image='products/supporting/old-angle.jpg',
        )
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_edit', args=[self.product.id]), {
            'store': self.store.id,
            'supporting_images': [self._uploaded_image('new-angle.jpg', color=(90, 90, 160))],
            'delete_supporting_images': [str(existing_image.id)],
            'name': self.product.name,
            'price': '2500.00',
            'category': self.category.id,
            'brand': '',
            'stock': '2',
            'available': 'on',
            'description': self.product.description,
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        self.assertFalse(ProductImage.objects.filter(id=existing_image.id).exists())
        self.assertEqual(self.product.supporting_images.count(), 1)

    def test_merchant_cannot_delete_gallery_image_from_another_product(self):
        other_product = Product.objects.get(slug='other-phone')
        other_image = ProductImage.objects.create(
            product=other_product,
            image='products/supporting/other-angle.jpg',
        )
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_edit', args=[self.product.id]), {
            'store': self.store.id,
            'delete_supporting_images': [str(other_image.id)],
            'name': self.product.name,
            'price': '2500.00',
            'category': self.category.id,
            'brand': '',
            'stock': '2',
            'available': 'on',
            'description': self.product.description,
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        self.assertTrue(ProductImage.objects.filter(id=other_image.id).exists())

    def test_merchant_can_pause_own_product(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_edit', args=[self.product.id]), {
            'store': self.store.id,
            'name': self.product.name,
            'price': '2500.00',
            'category': self.category.id,
            'brand': '',
            'stock': '2',
            'description': self.product.description,
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        self.product.refresh_from_db()
        self.assertFalse(self.product.available)

    def test_merchant_cannot_edit_another_merchants_product(self):
        other_product = Product.objects.get(slug='other-phone')
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_product_edit', args=[other_product.id]))

        self.assertEqual(response.status_code, 404)

    def test_customer_cannot_access_merchant_orders(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('merchant_orders'))

        self.assertEqual(response.status_code, 403)

    def test_merchant_can_view_own_store_orders(self):
        other_product = Product.objects.get(slug='other-phone')
        other_order = Order.objects.create(
            user=self.customer,
            first_name='Customer',
            last_name='Two',
            email='customer2@example.com',
            address='Mazabuka',
            city='Mazabuka',
            postal_code='10101',
            phone='260966000000',
            status='paid',
            subtotal=Decimal('3000.00'),
            shipping=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('3000.00'),
            payment_method='mobile_money',
            payment_status='completed',
        )
        OrderItem.objects.create(
            order=other_order,
            product=other_product,
            price=Decimal('3000.00'),
            quantity=1,
        )
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Order #{self.order.id}')
        self.assertContains(response, reverse('merchant_order_detail', args=[self.order.id]))
        self.assertNotContains(response, f'Order #{other_order.id}')

    def test_merchant_can_view_own_order_detail(self):
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_order_detail', args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customer One')
        self.assertContains(response, 'Merchant Phone')
        self.assertContains(response, '260977000000')

    def test_merchant_cannot_view_another_store_order_detail(self):
        other_product = Product.objects.get(slug='other-phone')
        other_order = Order.objects.create(
            user=self.customer,
            first_name='Customer',
            last_name='Two',
            email='customer2@example.com',
            address='Mazabuka',
            city='Mazabuka',
            postal_code='10101',
            phone='260966000000',
            status='paid',
            subtotal=Decimal('3000.00'),
            shipping=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('3000.00'),
            payment_method='mobile_money',
            payment_status='completed',
        )
        OrderItem.objects.create(
            order=other_order,
            product=other_product,
            price=Decimal('3000.00'),
            quantity=1,
        )
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_order_detail', args=[other_order.id]))

        self.assertEqual(response.status_code, 404)

    def test_merchant_can_save_order_fulfillment_notes(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_order_update', args=[self.order.id]), {
            'action': 'save_fulfillment',
            'dispatch_reference': 'Courier-123',
            'fulfillment_notes': 'Packed in a sealed bag.',
        })

        self.assertRedirects(response, reverse('merchant_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.dispatch_reference, 'Courier-123')
        self.assertEqual(self.order.fulfillment_notes, 'Packed in a sealed bag.')

    def test_merchant_can_mark_paid_order_as_packing(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_order_update', args=[self.order.id]), {
            'action': 'mark_packing',
        })

        self.assertRedirects(response, reverse('merchant_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'packing')

    def test_merchant_can_mark_packing_order_as_dispatched(self):
        self.order.status = 'packing'
        self.order.dispatch_reference = 'Courier-123'
        self.order.save(update_fields=['status', 'dispatch_reference'])
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_order_update', args=[self.order.id]), {
            'action': 'mark_dispatched',
        })

        self.assertRedirects(response, reverse('merchant_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'dispatched')
        self.assertEqual(self.order.dispatch_reference, 'Courier-123')

    def test_merchant_cannot_dispatch_unpacked_order(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_order_update', args=[self.order.id]), {
            'action': 'mark_dispatched',
        })

        self.assertRedirects(response, reverse('merchant_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')

    def test_merchant_cannot_update_another_store_order(self):
        other_product = Product.objects.get(slug='other-phone')
        other_order = Order.objects.create(
            user=self.customer,
            first_name='Customer',
            last_name='Two',
            email='customer2@example.com',
            address='Mazabuka',
            city='Mazabuka',
            postal_code='10101',
            phone='260966000000',
            status='paid',
            subtotal=Decimal('3000.00'),
            shipping=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('3000.00'),
            payment_method='mobile_money',
            payment_status='completed',
        )
        OrderItem.objects.create(
            order=other_order,
            product=other_product,
            price=Decimal('3000.00'),
            quantity=1,
        )
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_order_update', args=[other_order.id]), {
            'action': 'mark_packing',
        })

        self.assertEqual(response.status_code, 404)
        other_order.refresh_from_db()
        self.assertEqual(other_order.status, 'paid')
