from django.shortcuts import render, redirect
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.views.decorators.http import require_http_methods
from store.forms import EmailOrPhoneAuthenticationForm
from django.contrib import messages
from .forms import ProfileUpdateForm
from .phone_verification import send_phone_verification_code


@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Custom login view that accepts email, phone number, or username.
    """
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        form = EmailOrPhoneAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            backend_path = 'users.backends.EmailOrPhoneBackend'
            user.backend = backend_path
            login(request, user, backend=backend_path)
            messages.success(request, f'Welcome back, {user.first_name or user.username}!')
            
            # Redirect to next page or home
            next_page = request.GET.get('next', 'home')
            return redirect(next_page)
        else:
            messages.error(request, 'Invalid email/phone/username or password.')
    else:
        form = EmailOrPhoneAuthenticationForm()
    
    return render(request, 'registration/login.html', {'form': form})


@login_required
def profile_view(request):
    profile_form = ProfileUpdateForm(instance=request.user)
    password_form = PasswordChangeForm(user=request.user)

    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'profile':
            profile_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
            if profile_form.is_valid():
                user = profile_form.save()
                if getattr(profile_form, 'phone_changed', False):
                    sent, message = send_phone_verification_code(user, user.client_profile.phone_number)
                    request.session['pending_user_id'] = user.id
                    if sent:
                        messages.warning(request, 'Phone number updated. Verify Phone to finish securing your account.')
                    else:
                        messages.warning(request, message)
                else:
                    messages.success(request, 'Your profile has been updated.')
                return redirect('profile')
            messages.error(request, 'Please correct the profile form errors.')

        elif form_type == 'verify_phone':
            profile = getattr(request.user, 'client_profile', None)
            phone = getattr(profile, 'phone_number', '')
            sent, message = send_phone_verification_code(request.user, phone)
            request.session['pending_user_id'] = request.user.id
            if sent:
                messages.success(request, message)
                return redirect('verify_otp')
            messages.error(request, message)
            return redirect('profile')

        elif form_type == 'password':
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password has been updated.')
                return redirect('profile')
            messages.error(request, 'Please correct the password form errors.')

    return render(request, 'registration/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
    })
