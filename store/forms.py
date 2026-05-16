from django import forms
from django.contrib.auth.forms import UserCreationForm
from users.models import User
from .models import Order

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    phone = forms.CharField(max_length=20, required=True)

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        # Allow leading +, digits, and common separators; normalize to + and digits only
        normalized = ''.join(ch for ch in phone if ch.isdigit() or ch == '+')
        # Ensure + appears at most once and only at the start
        if normalized.count('+') > 1 or ('+' in normalized and not normalized.startswith('+')):
            raise forms.ValidationError('Invalid phone number format.')
        # Count digits to ensure a complete number (minimum 9 digits)
        digits = ''.join(ch for ch in normalized if ch.isdigit())
        if len(digits) < 9:
            raise forms.ValidationError('Please enter a complete phone number (at least 9 digits).')
        return normalized
    
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        # mark as client and keep inactive until phone verified
        user.is_client = True
        user.is_active = False
        if commit:
            user.save()
            # create or update client profile with phone
            from users.models import ClientProfile
            ClientProfile.objects.update_or_create(
                user=user,
                defaults={
                    'phone_number': self.cleaned_data.get('phone', ''),
                    'address': ''
                }
            )
        return user

class CheckoutForm(forms.Form):
    first_name = forms.CharField(max_length=100, required=True)
    last_name = forms.CharField(max_length=100, required=True)
    email = forms.EmailField(required=False)
    address = forms.CharField(max_length=255, required=False)
    city = forms.CharField(max_length=100, required=False)
    postal_code = forms.CharField(max_length=20, required=False)
    phone = forms.CharField(max_length=20, required=True)

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get('payment_method')
        if payment_method == 'mobile_money':
            # Require all fields for mobile money
            required_fields = ['email', 'address', 'city', 'postal_code']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Mobile Money payment.')
        return cleaned_data
    PAYMENT_CHOICES = [
        ('mobile_money', 'Mobile Money'),
        ('cash', 'Cash on Delivery'),
    ]
    
    payment_method = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        widget=forms.RadioSelect,
        required=True
    )
