from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
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
from .models import Category, MerchantPayout, Order, OrderItem, PayoutBatch, Product, ProductImage


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
        self.finance_user = User.objects.create_user(
            username='finance',
            password='password',
            role=User.Role.FINANCE_ADMINISTRATOR,
        )
        self.delivery_user = User.objects.create_user(
            username='delivery',
            password='password',
            role=User.Role.DELIVERY_PARTNER,
        )
        self.other_delivery_user = User.objects.create_user(
            username='other-delivery',
            password='password',
            role=User.Role.DELIVERY_PARTNER,
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

    def test_customer_order_confirmation_shows_tracking_steps(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('order_confirmation', args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order tracking')
        self.assertContains(response, 'Payment Awaiting')
        self.assertContains(response, 'Paid')
        self.assertContains(response, 'Packing')
        self.assertContains(response, 'Dispatched')
        self.assertContains(response, 'Delivered / Closed')

    def test_customer_order_history_shows_tracking_steps(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('order_history'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order tracking')
        self.assertContains(response, f'Order #{self.order.id}')
        self.assertContains(response, 'View Details')
        self.assertContains(response, 'Delivered / Closed')

    def test_customer_tracking_shows_delivery_details(self):
        self.order.status = 'delivered'
        self.order.dispatch_reference = 'Courier-123'
        self.order.delivery_partner = self.delivery_user
        self.order.delivery_confirmed_by = self.delivery_user
        self.order.delivered_at = timezone.now()
        self.order.delivery_notes = 'Handed to Customer One.'
        self.order.save(update_fields=[
            'status',
            'dispatch_reference',
            'delivery_partner',
            'delivery_confirmed_by',
            'delivered_at',
            'delivery_notes',
        ])
        self.client.force_login(self.customer)

        response = self.client.get(reverse('order_confirmation', args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delivered')
        self.assertContains(response, 'Dispatch reference')
        self.assertContains(response, 'Courier-123')
        self.assertContains(response, 'Delivery partner')
        self.assertContains(response, 'delivery')
        self.assertContains(response, 'Delivered at')
        self.assertContains(response, 'Handed to Customer One.')

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
            'offline_stock': '0',
            'low_stock_threshold': '5',
            'available': 'on',
            'description': 'Warm jacket',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        product = Product.objects.get(slug='fresh-jacket')
        self.assertEqual(product.store, self.store)
        self.assertEqual(product.price, Decimal('650.00'))
        self.assertEqual(product.stock, 4)
        self.assertTrue(product.available)
        self.assertEqual(product.publication_status, 'published')

    def test_merchant_can_save_product_as_draft(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_create'), {
            'store': self.store.id,
            'image': self._uploaded_image(),
            'name': 'Draft Jacket',
            'price': '450.00',
            'category': self.category.id,
            'brand': '',
            'stock': '4',
            'offline_stock': '2',
            'low_stock_threshold': '1',
            'available': 'on',
            'description': 'Draft product',
            'submit_action': 'draft',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        product = Product.objects.get(slug='draft-jacket')
        self.assertEqual(product.publication_status, 'draft')
        self.assertFalse(product.available)
        self.assertEqual(product.offline_stock, 2)
        self.assertEqual(product.low_stock_threshold, 1)

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
            'offline_stock': '0',
            'low_stock_threshold': '5',
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
            'offline_stock': '0',
            'low_stock_threshold': '5',
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
            'offline_stock': '0',
            'low_stock_threshold': '5',
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
            'offline_stock': '0',
            'low_stock_threshold': '5',
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
            'offline_stock': '1',
            'low_stock_threshold': '2',
            'available': 'on',
            'description': 'Updated description',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Updated Merchant Phone')
        self.assertEqual(self.product.price, Decimal('2400.00'))
        self.assertEqual(self.product.stock, 7)
        self.assertEqual(self.product.offline_stock, 1)
        self.assertEqual(self.product.low_stock_threshold, 2)
        self.assertTrue(self.product.available)

    def test_merchant_can_duplicate_product_as_draft(self):
        ProductImage.objects.create(
            product=self.product,
            image='products/supporting/old-angle.jpg',
        )
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_duplicate', args=[self.product.id]))

        duplicate = Product.objects.get(name='Merchant Phone Copy')
        self.assertRedirects(response, reverse('merchant_product_edit', args=[duplicate.id]))
        self.assertEqual(duplicate.store, self.store)
        self.assertEqual(duplicate.publication_status, 'draft')
        self.assertFalse(duplicate.available)
        self.assertEqual(duplicate.stock, 0)
        self.assertEqual(duplicate.supporting_images.count(), 1)

    def test_merchant_cannot_duplicate_another_merchants_product(self):
        other_product = Product.objects.get(slug='other-phone')
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_duplicate', args=[other_product.id]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Product.objects.filter(name='Other Phone Copy').exists())

    def test_merchant_can_update_product_inventory_from_dashboard(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_inventory_update', args=[self.product.id]), {
            'stock': '9',
            'offline_stock': '4',
            'low_stock_threshold': '2',
            'available': 'on',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 9)
        self.assertEqual(self.product.offline_stock, 4)
        self.assertEqual(self.product.low_stock_threshold, 2)
        self.assertTrue(self.product.available)

    def test_inventory_update_can_return_json_for_inline_dashboard_update(self):
        self.client.force_login(self.merchant_user)

        response = self.client.post(
            reverse('merchant_product_inventory_update', args=[self.product.id]),
            {
                'stock': '1',
                'offline_stock': '4',
                'low_stock_threshold': '2',
                'available': 'on',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['status'])
        self.assertEqual(payload['product']['stock'], 1)
        self.assertEqual(payload['product']['offline_stock'], 4)
        self.assertTrue(payload['product']['is_low_stock'])

    def test_inventory_update_keeps_drafts_not_live(self):
        self.product.publication_status = 'draft'
        self.product.available = False
        self.product.save(update_fields=['publication_status', 'available'])
        self.client.force_login(self.merchant_user)

        response = self.client.post(reverse('merchant_product_inventory_update', args=[self.product.id]), {
            'stock': '9',
            'offline_stock': '4',
            'low_stock_threshold': '2',
            'available': 'on',
        })

        self.assertRedirects(response, reverse('merchant_dashboard'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 9)
        self.assertFalse(self.product.available)

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
            'offline_stock': '0',
            'low_stock_threshold': '5',
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
            'offline_stock': '0',
            'low_stock_threshold': '5',
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
            'offline_stock': '0',
            'low_stock_threshold': '5',
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

    def test_customer_cannot_access_merchant_payouts(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('merchant_payouts'))

        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_access_finance_payouts(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('finance_payouts'))

        self.assertEqual(response.status_code, 403)

    def test_merchant_cannot_access_finance_payouts(self):
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('finance_payouts'))

        self.assertEqual(response.status_code, 403)

    def test_merchant_can_view_payout_summary_for_own_items(self):
        other_product = Product.objects.get(slug='other-phone')
        mixed_order = Order.objects.create(
            user=self.customer,
            first_name='Customer',
            last_name='Mixed',
            email='mixed@example.com',
            address='Mazabuka',
            city='Mazabuka',
            postal_code='10101',
            phone='260977111111',
            status='delivered',
            subtotal=Decimal('5500.00'),
            shipping=Decimal('0.00'),
            tax=Decimal('0.00'),
            total=Decimal('5500.00'),
            payment_method='mobile_money',
            payment_status='completed',
        )
        OrderItem.objects.create(
            order=mixed_order,
            product=self.product,
            price=Decimal('2500.00'),
            quantity=1,
        )
        OrderItem.objects.create(
            order=mixed_order,
            product=other_product,
            price=Decimal('3000.00'),
            quantity=1,
        )
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_payouts'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['gross_paid_total'], Decimal('5000.00'))
        self.assertEqual(response.context['ready_for_payout'], Decimal('2500.00'))
        self.assertEqual(response.context['pending_fulfillment_total'], Decimal('2500.00'))
        self.assertContains(response, 'Merchant Phone')
        self.assertNotContains(response, 'Other Phone')

    def test_merchant_payouts_sync_records_and_preserve_paid_status(self):
        order_item = self.order.items.get(product=self.product)
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_payouts'))

        self.assertEqual(response.status_code, 200)
        payout = MerchantPayout.objects.get(order_item=order_item)
        self.assertEqual(payout.status, 'pending')
        self.assertEqual(payout.amount, Decimal('2500.00'))
        self.assertEqual(payout.platform_fee, Decimal('0.00'))
        self.assertEqual(payout.net_amount, Decimal('2500.00'))

        self.order.status = 'delivered'
        self.order.save(update_fields=['status'])
        self.client.get(reverse('merchant_payouts'))
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'ready')

        paid_at = timezone.now()
        batch = PayoutBatch.objects.create(
            reference='MERCHANT-BATCH-001',
            processed_by=self.finance_user,
            gross_total=Decimal('2500.00'),
            platform_fee_total=Decimal('0.00'),
            net_total=Decimal('2500.00'),
            paid_at=paid_at,
        )
        payout.status = 'paid'
        payout.paid_at = paid_at
        payout.batch = batch
        payout.save(update_fields=['status', 'paid_at', 'batch'])
        self.order.status = 'cleared'
        self.order.save(update_fields=['status'])

        response = self.client.get(reverse('merchant_payouts'))
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'paid')
        self.assertEqual(payout.batch, batch)
        self.assertEqual(response.context['ready_for_payout'], Decimal('0'))
        self.assertEqual(response.context['paid_out_total'], Decimal('2500.00'))
        self.assertContains(response, 'Batch reference')
        self.assertContains(response, 'Paid at')
        self.assertContains(response, 'MERCHANT-BATCH-001')
        self.assertContains(response, paid_at.strftime('%Y-%m-%d'))

    @override_settings(MERCHANT_PAYOUT_FEE_RATE='0.10')
    def test_merchant_payouts_calculate_platform_fee_and_net_amount(self):
        self.client.force_login(self.merchant_user)

        response = self.client.get(reverse('merchant_payouts'))

        payout = MerchantPayout.objects.get(order_item__order=self.order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payout.amount, Decimal('2500.00'))
        self.assertEqual(payout.platform_fee, Decimal('250.00'))
        self.assertEqual(payout.net_amount, Decimal('2250.00'))
        self.assertEqual(response.context['platform_fee_total'], Decimal('250.00'))
        self.assertEqual(response.context['pending_fulfillment_total'], Decimal('2250.00'))

    def test_finance_can_view_and_export_payout_reconciliation(self):
        self.order.status = 'delivered'
        self.order.save(update_fields=['status'])
        self.client.force_login(self.finance_user)

        response = self.client.get(reverse('finance_payouts'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['ready_total'], Decimal('2500.00'))
        self.assertEqual(response.context['platform_fee_total'], Decimal('0.00'))
        self.assertContains(response, 'Merchant payout reconciliation')
        self.assertContains(response, 'Merchant Store')
        self.assertContains(response, 'Merchant Phone')

        export_response = self.client.get(reverse('finance_payouts'), {'export': 'csv'})
        csv_body = export_response.content.decode()

        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response['Content-Type'], 'text/csv')
        self.assertIn('Payout ID,Store,Order,Product', csv_body)
        self.assertIn('Gross Amount,Platform Fee,Net Payout', csv_body)
        self.assertIn('Merchant Store', csv_body)
        self.assertIn('Merchant Phone', csv_body)

    def test_finance_can_hold_refresh_and_create_paid_payout_batch(self):
        self.client.force_login(self.finance_user)
        self.client.get(reverse('finance_payouts'))
        pending_payout = MerchantPayout.objects.get(order_item__order=self.order)

        response = self.client.post(reverse('finance_payouts'), {
            'action': 'hold',
            'payout_ids': [str(pending_payout.id)],
        })

        self.assertRedirects(response, reverse('finance_payouts'))
        pending_payout.refresh_from_db()
        self.assertEqual(pending_payout.status, 'held')

        response = self.client.post(reverse('finance_payouts'), {
            'action': 'refresh',
            'payout_ids': [str(pending_payout.id)],
        })

        self.assertRedirects(response, reverse('finance_payouts'))
        pending_payout.refresh_from_db()
        self.assertEqual(pending_payout.status, 'held')

        self.order.status = 'delivered'
        self.order.save(update_fields=['status'])
        pending_payout.status = 'ready'
        pending_payout.save(update_fields=['status'])

        response = self.client.post(reverse('finance_payouts'), {
            'action': 'mark_paid',
            'payout_ids': [str(pending_payout.id)],
            'batch_reference': 'BANK-001',
            'batch_note': 'Mobile money merchant payout',
        })

        self.assertRedirects(response, reverse('finance_payouts'))
        pending_payout.refresh_from_db()
        self.assertEqual(pending_payout.status, 'paid')
        self.assertIsNotNone(pending_payout.paid_at)
        batch = PayoutBatch.objects.get(reference='BANK-001')
        self.assertEqual(pending_payout.batch, batch)
        self.assertEqual(batch.gross_total, Decimal('2500.00'))
        self.assertEqual(batch.platform_fee_total, Decimal('0.00'))
        self.assertEqual(batch.net_total, Decimal('2500.00'))
        self.assertEqual(batch.processed_by, self.finance_user)
        self.assertEqual(batch.note, 'Mobile money merchant payout')

    def test_finance_paid_batch_requires_unique_reference(self):
        self.order.status = 'delivered'
        self.order.save(update_fields=['status'])
        self.client.force_login(self.finance_user)
        self.client.get(reverse('finance_payouts'))
        payout = MerchantPayout.objects.get(order_item__order=self.order)

        response = self.client.post(reverse('finance_payouts'), {
            'action': 'mark_paid',
            'payout_ids': [str(payout.id)],
        })

        self.assertRedirects(response, reverse('finance_payouts'))
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'ready')
        self.assertFalse(PayoutBatch.objects.exists())

        PayoutBatch.objects.create(
            reference='DUPLICATE',
            processed_by=self.finance_user,
            gross_total=Decimal('0.00'),
            platform_fee_total=Decimal('0.00'),
            net_total=Decimal('0.00'),
            paid_at=timezone.now(),
        )
        response = self.client.post(reverse('finance_payouts'), {
            'action': 'mark_paid',
            'payout_ids': [str(payout.id)],
            'batch_reference': 'DUPLICATE',
        })

        self.assertRedirects(response, reverse('finance_payouts'))
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'ready')
        self.assertEqual(PayoutBatch.objects.count(), 1)

    def test_finance_can_view_and_export_payout_batch_detail(self):
        self.order.status = 'delivered'
        self.order.save(update_fields=['status'])
        self.client.force_login(self.finance_user)
        self.client.get(reverse('finance_payouts'))
        payout = MerchantPayout.objects.get(order_item__order=self.order)
        self.client.post(reverse('finance_payouts'), {
            'action': 'mark_paid',
            'payout_ids': [str(payout.id)],
            'batch_reference': 'BANK-DETAIL-001',
            'batch_note': 'Detail test batch',
        })
        batch = PayoutBatch.objects.get(reference='BANK-DETAIL-001')

        response = self.client.get(reverse('finance_payout_batch_detail', args=[batch.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['batch'], batch)
        self.assertEqual(response.context['payout_count'], 1)
        self.assertEqual(response.context['gross_total'], Decimal('2500.00'))
        self.assertEqual(response.context['net_total'], Decimal('2500.00'))
        self.assertContains(response, 'BANK-DETAIL-001')
        self.assertContains(response, 'Merchant Phone')

        export_response = self.client.get(
            reverse('finance_payout_batch_detail', args=[batch.id]),
            {'export': 'csv'},
        )
        csv_body = export_response.content.decode()

        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response['Content-Type'], 'text/csv')
        self.assertIn('BANK-DETAIL-001', csv_body)
        self.assertIn('Merchant Phone', csv_body)

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

    def test_customer_cannot_access_delivery_orders(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('delivery_orders'))

        self.assertEqual(response.status_code, 403)

    def test_delivery_partner_can_claim_dispatched_order(self):
        self.order.status = 'dispatched'
        self.order.dispatch_reference = 'Courier-123'
        self.order.save(update_fields=['status', 'dispatch_reference'])
        self.client.force_login(self.delivery_user)

        response = self.client.get(reverse('delivery_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order #')
        self.assertContains(response, 'Claim delivery')
        self.assertContains(response, 'Courier-123')

        response = self.client.post(reverse('delivery_order_update', args=[self.order.id]), {
            'action': 'claim',
        })

        self.assertRedirects(response, reverse('delivery_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_partner, self.delivery_user)
        self.assertEqual(self.order.status, 'dispatched')

    def test_delivery_partner_can_mark_assigned_order_delivered_and_release_payout(self):
        self.order.status = 'dispatched'
        self.order.dispatch_reference = 'Courier-123'
        self.order.delivery_partner = self.delivery_user
        self.order.save(update_fields=['status', 'dispatch_reference', 'delivery_partner'])
        self.client.force_login(self.delivery_user)

        response = self.client.post(reverse('delivery_order_update', args=[self.order.id]), {
            'action': 'mark_delivered',
            'delivery_notes': 'Handed to Customer One.',
        })

        self.assertRedirects(response, reverse('delivery_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'delivered')
        self.assertIsNotNone(self.order.delivered_at)
        self.assertEqual(self.order.delivery_confirmed_by, self.delivery_user)
        self.assertEqual(self.order.delivery_notes, 'Handed to Customer One.')

        self.client.force_login(self.merchant_user)
        self.client.get(reverse('merchant_payouts'))
        payout = MerchantPayout.objects.get(order_item__order=self.order)
        self.assertEqual(payout.status, 'ready')

    def test_delivery_partner_cannot_complete_unassigned_order(self):
        self.order.status = 'dispatched'
        self.order.save(update_fields=['status'])
        self.client.force_login(self.other_delivery_user)

        response = self.client.post(reverse('delivery_order_update', args=[self.order.id]), {
            'action': 'mark_delivered',
            'delivery_notes': 'Attempted by another rider.',
        })

        self.assertRedirects(response, reverse('delivery_orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'dispatched')
        self.assertIsNone(self.order.delivered_at)
        self.assertEqual(self.order.delivery_notes, '')

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
