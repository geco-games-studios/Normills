from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.views.decorators.http import require_http_methods
from store.forms import EmailOrPhoneAuthenticationForm
from django.contrib import messages


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
            login(request, user)
            messages.success(request, f'Welcome back, {user.first_name or user.username}!')
            
            # Redirect to next page or home
            next_page = request.GET.get('next', 'home')
            return redirect(next_page)
        else:
            messages.error(request, 'Invalid email/phone/username or password.')
    else:
        form = EmailOrPhoneAuthenticationForm()
    
    return render(request, 'registration/login.html', {'form': form})

