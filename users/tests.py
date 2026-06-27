from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase


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
