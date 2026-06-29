import re
from io import BytesIO
from django import forms
from django.core.files.base import ContentFile
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from PIL import Image
from users.models import User
from users.phone_verification import normalize_phone
from .models import Brand, Category, Order, Product


MAX_PRODUCT_IMAGE_SIZE = 8 * 1024 * 1024
MAX_PRODUCT_IMAGE_DIMENSION = 1600
PRODUCT_IMAGE_FORMATS = {
    'image/jpeg': ('JPEG', '.jpg'),
    'image/png': ('PNG', '.png'),
    'image/webp': ('WEBP', '.webp'),
}


def prepare_product_image(image):
    content_type = getattr(image, 'content_type', '')
    if not content_type:
        return image

    if image.size > MAX_PRODUCT_IMAGE_SIZE:
        raise forms.ValidationError('Upload an image smaller than 8 MB.')

    if content_type not in PRODUCT_IMAGE_FORMATS:
        raise forms.ValidationError('Upload a JPG, PNG, or WebP image.')

    output_format, extension = PRODUCT_IMAGE_FORMATS[content_type]
    try:
        image.file.seek(0)
        source = Image.open(image.file)
        source.load()
    except Exception as exc:
        raise forms.ValidationError('Upload a valid image file.') from exc

    source.thumbnail(
        (MAX_PRODUCT_IMAGE_DIMENSION, MAX_PRODUCT_IMAGE_DIMENSION),
        Image.Resampling.LANCZOS,
    )

    if output_format == 'JPEG' and source.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', source.size, (255, 255, 255))
        if source.mode == 'P':
            source = source.convert('RGBA')
        background.paste(source, mask=source.getchannel('A') if source.mode in ('RGBA', 'LA') else None)
        source = background
    elif output_format == 'JPEG' and source.mode != 'RGB':
        source = source.convert('RGB')

    output = BytesIO()
    save_options = {'format': output_format}
    if output_format == 'JPEG':
        save_options.update({'quality': 82, 'optimize': True})
    elif output_format in {'PNG', 'WEBP'}:
        save_options.update({'optimize': True})
    source.save(output, **save_options)

    base_name = slugify(image.name.rsplit('.', 1)[0]) or 'product-image'
    return ContentFile(output.getvalue(), name=f'{base_name}{extension}')


class CustomUserCreationForm(UserCreationForm):
    username = forms.CharField(widget=forms.HiddenInput(), required=False)
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    phone = forms.CharField(max_length=20, required=True)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email

    def clean_phone(self):
        digits = normalize_phone(self.cleaned_data.get('phone') or '')
        if not digits:
            raise forms.ValidationError('Please enter a complete phone number (including country code).')
        return digits

    def _generate_username(self, email, phone=''):
        base_value = email.split('@')[0] if email else f"normils-{phone}"
        base = re.sub(r'[^a-zA-Z0-9._+-]', '', base_value) or get_random_string(8)
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
        user.is_verified = False
        user.username = self.cleaned_data.get('username') or self._generate_username(user.email, self.cleaned_data.get('phone', ''))
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


class MerchantProductForm(forms.ModelForm):
    image = forms.ImageField(required=True)

    class Meta:
        model = Product
        fields = (
            'store',
            'image',
            'name',
            'price',
            'category',
            'brand',
            'stock',
            'offline_stock',
            'low_stock_threshold',
            'available',
            'description',
        )
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, stores=None, require_image=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].required = require_image
        self.fields['store'].queryset = stores if stores is not None else self.fields['store'].queryset.none()
        self.fields['category'].queryset = Category.objects.order_by('name')
        self.fields['brand'].queryset = Brand.objects.order_by('name')
        self.fields['brand'].required = False
        self.fields['description'].required = False
        self.fields['stock'].min_value = 0
        self.fields['offline_stock'].min_value = 0
        self.fields['low_stock_threshold'].min_value = 0

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'h-5 w-5 border border-gray-300 text-black')
                continue
            field.widget.attrs.setdefault(
                'class',
                'w-full border border-gray-300 px-4 py-3 text-base outline-none focus:border-black',
            )

    def save(self, commit=True):
        product = super().save(commit=False)
        if not product.slug:
            base_slug = slugify(product.name) or f"product-{get_random_string(6)}"
            slug = base_slug
            suffix = 2
            while Product.objects.filter(slug=slug).exclude(pk=product.pk).exists():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            product.slug = slug
        if commit:
            product.save()
            self.save_m2m()
        return product

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image:
            return image

        return prepare_product_image(image)


class CheckoutForm(forms.Form):
    first_name = forms.CharField(max_length=100, required=True)
    last_name = forms.CharField(max_length=100, required=False)
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
