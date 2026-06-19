from django import forms
from django.contrib.auth import get_user_model

from .models import ClientProfile
from .phone_verification import normalize_phone


User = get_user_model()


class ProfileUpdateForm(forms.ModelForm):
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={
        'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-black',
    }))
    phone = forms.CharField(max_length=20, required=True, widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-black',
        'placeholder': '0977123456',
    }))

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone', 'profile_picture')
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-black',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-black',
            }),
            'profile_picture': forms.ClearableFileInput(attrs={
                'class': 'w-full text-sm text-gray-700',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = getattr(self.instance, 'client_profile', None)
        self.fields['email'].initial = self.instance.email
        self.fields['phone'].initial = getattr(profile, 'phone_number', '')

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and User.objects.exclude(pk=self.instance.pk).filter(email__iexact=email).exists():
            raise forms.ValidationError('That email is already in use.')
        return email

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get('phone') or '')
        if not phone:
            raise forms.ValidationError('Please enter a valid phone number.')
        existing = ClientProfile.objects.exclude(user=self.instance).filter(phone_number__iexact=phone).exists()
        if existing:
            raise forms.ValidationError('That phone number is already in use.')
        return phone

    def save(self, commit=True):
        old_phone = ''
        if self.instance.pk:
            old_phone = getattr(getattr(self.instance, 'client_profile', None), 'phone_number', '')

        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email') or ''
        phone = self.cleaned_data['phone']
        phone_changed = normalize_phone(old_phone) != phone
        if phone_changed:
            user.is_verified = False
        if commit:
            user.save()
            profile, _ = ClientProfile.objects.get_or_create(user=user)
            profile.phone_number = phone
            profile.save(update_fields=['phone_number', 'updated_at'])
        self.phone_changed = phone_changed
        return user
