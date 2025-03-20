from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, StoreOwnerProfile

# Custom User Admin
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'is_store_owner', 'is_client', 'is_staff', 'is_superuser')
    list_filter = ('is_store_owner', 'is_client', 'is_staff', 'is_superuser')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_store_owner', 'is_client')}),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )

# Register the custom User model
admin.site.register(User, CustomUserAdmin)

# Store Owner Profile Admin
@admin.register(StoreOwnerProfile)
class StoreOwnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'store_name', 'phone_number', 'address')
    search_fields = ('user__username', 'store_name')

# Client Profile Admin
# @admin.register(ClientProfile)
# class ClientProfileAdmin(admin.ModelAdmin):
#     list_display = ('user', 'phone_number', 'address')
#     search_fields = ('user__username',)
