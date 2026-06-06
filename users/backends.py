from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()

class EmailOrPhoneBackend(ModelBackend):
    """
    Custom authentication backend that allows login with email or phone number.
    """

    def _normalize_phone(self, phone):
        if not phone or not isinstance(phone, str):
            return phone
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if digits.startswith('00'):
            digits = digits[2:]
        if digits.startswith('0') and len(digits) == 10:
            digits = '260' + digits[1:]
        elif len(digits) == 9:
            digits = '260' + digits
        return digits
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate with email, phone number, or username.
        """
        normalized_phone = self._normalize_phone(username)
        try:
            # Try to find user by email or phone number only
            if normalized_phone:
                user = User.objects.get(
                    Q(email__iexact=username) |
                    Q(client_profile__phone_number__iexact=normalized_phone)
                )
            else:
                user = User.objects.get(Q(email__iexact=username))
        except User.DoesNotExist:
            User().set_password(password)
            return None
        
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        
        return None
    
    def get_user(self, user_id):
        """
        Get user by ID.
        """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
