import re
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.utils.crypto import get_random_string
from users.models import User
from .models import Order

class CustomUserCreationForm(UserCreationForm):
    username = forms.CharField(widget=forms.HiddenInput(), required=False)
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    phone = forms.CharField(max_length=20, required=True)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if phone.startswith('00'):
            digits = digits[2:]
        if phone.startswith('0') and not phone.startswith('00') and len(digits) == 10:
            digits = '260' + digits[1:]
        elif len(digits) == 9:
            digits = '260' + digits
        if len(digits) < 12:
            raise forms.ValidationError('Please enter a complete phone number (including country code).')
        if not digits.isdigit():
            raise forms.ValidationError('Invalid phone number format.')
        return digits

    def _generate_username(self, email):
        base = re.sub(r'[^a-zA-Z0-9._+-]', '', email.split('@')[0]) or get_random_string(8)
        username = base[:30]
        while User.objects.filter(username=username).exists():
            username = f"{base[:24]}{get_random_string(6)}"
        return username
    
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'phone', 'password1', 'password2')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.is_client = True
        user.is_active = False
        user.username = self.cleaned_data.get('username') or self._generate_username(user.email)
        if commit:
            user.save()
            from users.models import ClientProfile
            ClientProfile.objects.update_or_create(
                user=user,
                defaults={
                    'phone_number': self.cleaned_data.get('phone', ''),
                    'address': ''
                }
            )
        return user


class EmailOrPhoneAuthenticationForm(AuthenticationForm):
    """
    Custom authentication form that accepts email or phone number.
    """
    username = forms.CharField(
        label="Email or Phone Number",
        max_length=254,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
            'autofocus': True,
            'placeholder': 'Enter email or phone number'
        })
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 pr-10 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
            'autocomplete': 'current-password',
        })
    )
    
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields['username'].label = "Email, Phone Number, or Username"

class CheckoutForm(forms.Form):
    first_name = forms.CharField(max_length=100, required=True)
    last_name = forms.CharField(max_length=100, required=True)
    email = forms.EmailField(required=False)
    address = forms.CharField(max_length=255, required=False)
    city = forms.CharField(max_length=100, required=False)
    postal_code = forms.CharField(max_length=20, required=False)
    phone = forms.CharField(max_length=20, required=True)
    notes = forms.CharField(required=False, widget=forms.Textarea)

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get('payment_method')
        delivery_method = cleaned_data.get('delivery_method')
        if payment_method == 'mobile_money':
            required_fields = ['email']
            if delivery_method == 'delivery':
                required_fields.extend(['address', 'city'])
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Mobile Money payment.')
        if delivery_method == 'delivery':
            for field in ['address', 'city']:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for delivery.')
        return cleaned_data

    DELIVERY_CHOICES = [
        ('delivery', 'Delivery'),
        ('pickup', 'Pickup'),
    ]

    PAYMENT_CHOICES = [
        ('mobile_money', 'Mobile Money'),
        ('cash', 'Pay on delivery/pickup'),
    ]

    delivery_method = forms.ChoiceField(
        choices=DELIVERY_CHOICES,
        widget=forms.RadioSelect,
        required=True
    )
    
    payment_method = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        widget=forms.RadioSelect,
        required=True
    )
