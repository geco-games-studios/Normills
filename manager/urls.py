from django.urls import path
from . import views

urlpatterns = [
    path('store/<slug:store_slug>/', views.store_dashboard, name='store_dashboard'),
]