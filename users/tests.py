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
