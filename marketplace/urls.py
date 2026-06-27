from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from users import views as user_views
import importlib.util

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('store.urls')),
    path('users/', include('users.urls')),
    path('accounts/login/', user_views.login_view, name='login'),  # Custom login
    path('accounts/profile/', user_views.profile_view, name='profile'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/', include('django.contrib.auth.urls')),  # Include other auth URLs (password reset, etc.)
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),  # Direct logout URL
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG and importlib.util.find_spec('django_browser_reload'):
    urlpatterns.append(path('__reload__/', include('django_browser_reload.urls')))
