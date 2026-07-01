from django.contrib.auth import authenticate, get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .permissions import delivery_partner_required, finance_admin_required, merchant_required, moderator_required, platform_admin_required


class EmailOrPhoneBackendTests(TestCase):
    def test_duplicate_email_login_uses_matching_password(self):
        User = get_user_model()
        first_user = User.objects.create_user(
            username='first-user',
            email='same@example.com',
            password='first-password',
        )
        User.objects.create_user(
            username='second-user',
            email='same@example.com',
            password='second-password',
        )

        user = authenticate(username='same@example.com', password='first-password')

        self.assertEqual(user, first_user)


class UserRoleTests(TestCase):
    def test_new_user_defaults_to_customer_role(self):
        User = get_user_model()
        user = User.objects.create_user(username='customer', password='password')

        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.is_customer_role)
        self.assertFalse(user.can_access_merchant_centre)

    def test_merchant_role_can_access_merchant_centre(self):
        User = get_user_model()
        user = User.objects.create_user(
            username='merchant',
            password='password',
            role=User.Role.MERCHANT,
        )

        self.assertTrue(user.is_merchant_role)
        self.assertTrue(user.can_access_merchant_centre)

    def test_verified_merchant_badge_marks_user_as_verified_merchant(self):
        User = get_user_model()
        user = User.objects.create_user(
            username='trusted-merchant',
            password='password',
            role=User.Role.MERCHANT,
            trust_badges=[User.TrustBadge.VERIFIED_MERCHANT],
        )

        self.assertTrue(user.has_trust_badge(User.TrustBadge.VERIFIED_MERCHANT))
        self.assertTrue(user.is_verified_merchant_role)

    def test_finance_role_is_separate_from_moderation_role(self):
        User = get_user_model()
        finance_user = User.objects.create_user(
            username='finance',
            password='password',
            role=User.Role.FINANCE_ADMINISTRATOR,
        )
        moderator = User.objects.create_user(
            username='moderator',
            password='password',
            role=User.Role.MODERATOR,
        )

        self.assertTrue(finance_user.can_access_finance_admin)
        self.assertFalse(finance_user.can_access_moderation)
        self.assertTrue(moderator.can_access_moderation)
        self.assertFalse(moderator.can_access_finance_admin)

    def test_delivery_partner_role_accesses_delivery_centre_only(self):
        User = get_user_model()
        delivery_partner = User.objects.create_user(
            username='delivery',
            password='password',
            role=User.Role.DELIVERY_PARTNER,
        )
        merchant = User.objects.create_user(
            username='merchant-user',
            password='password',
            role=User.Role.MERCHANT,
        )

        self.assertTrue(delivery_partner.can_access_delivery_centre)
        self.assertFalse(delivery_partner.can_access_merchant_centre)
        self.assertFalse(delivery_partner.can_access_finance_admin)
        self.assertFalse(merchant.can_access_delivery_centre)

    def test_administrator_role_can_access_platform_admin(self):
        User = get_user_model()
        administrator = User.objects.create_user(
            username='administrator',
            password='password',
            role=User.Role.ADMINISTRATOR,
        )
        merchant = User.objects.create_user(
            username='merchant-user',
            password='password',
            role=User.Role.MERCHANT,
        )

        self.assertTrue(administrator.can_access_platform_admin)
        self.assertFalse(merchant.can_access_platform_admin)


class RolePermissionDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_for(self, user):
        request = self.factory.get('/protected/')
        request.user = user
        return request

    def _ok_view(self, request):
        return HttpResponse('ok')

    def test_merchant_required_allows_merchants(self):
        User = get_user_model()
        user = User.objects.create_user(username='merchant', role=User.Role.MERCHANT)

        response = merchant_required(self._ok_view)(self._request_for(user))

        self.assertEqual(response.status_code, 200)

    def test_merchant_required_blocks_customers(self):
        User = get_user_model()
        user = User.objects.create_user(username='customer')

        response = merchant_required(self._ok_view)(self._request_for(user))

        self.assertEqual(response.status_code, 403)

    def test_finance_admin_required_allows_only_finance_scope(self):
        User = get_user_model()
        finance_user = User.objects.create_user(username='finance', role=User.Role.FINANCE_ADMINISTRATOR)
        moderator = User.objects.create_user(username='moderator', role=User.Role.MODERATOR)

        self.assertEqual(finance_admin_required(self._ok_view)(self._request_for(finance_user)).status_code, 200)
        self.assertEqual(finance_admin_required(self._ok_view)(self._request_for(moderator)).status_code, 403)

    def test_delivery_partner_required_allows_only_delivery_scope(self):
        User = get_user_model()
        delivery_partner = User.objects.create_user(username='delivery', role=User.Role.DELIVERY_PARTNER)
        merchant = User.objects.create_user(username='merchant', role=User.Role.MERCHANT)

        self.assertEqual(delivery_partner_required(self._ok_view)(self._request_for(delivery_partner)).status_code, 200)
        self.assertEqual(delivery_partner_required(self._ok_view)(self._request_for(merchant)).status_code, 403)

    def test_moderator_required_allows_support_scope(self):
        User = get_user_model()
        support_user = User.objects.create_user(username='support', role=User.Role.SUPPORT_OFFICER)
        finance_user = User.objects.create_user(username='finance', role=User.Role.FINANCE_ADMINISTRATOR)

        self.assertEqual(moderator_required(self._ok_view)(self._request_for(support_user)).status_code, 200)
        self.assertEqual(moderator_required(self._ok_view)(self._request_for(finance_user)).status_code, 403)

    def test_platform_admin_required_blocks_merchants(self):
        User = get_user_model()
        administrator = User.objects.create_user(username='admin-role', role=User.Role.ADMINISTRATOR)
        merchant = User.objects.create_user(username='merchant-role', role=User.Role.MERCHANT)

        self.assertEqual(platform_admin_required(self._ok_view)(self._request_for(administrator)).status_code, 200)
        self.assertEqual(platform_admin_required(self._ok_view)(self._request_for(merchant)).status_code, 403)


class DashboardPermissionTests(TestCase):
    def test_customer_cannot_access_broad_admin_dashboard(self):
        User = get_user_model()
        customer = User.objects.create_user(username='customer', password='password')
        self.client.force_login(customer)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 403)

    def test_merchant_cannot_access_broad_admin_dashboard(self):
        User = get_user_model()
        merchant = User.objects.create_user(
            username='merchant',
            password='password',
            role=User.Role.MERCHANT,
        )
        self.client.force_login(merchant)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 403)
