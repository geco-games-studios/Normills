from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, StoreOwnerProfile, ClientProfile

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Signal handler to create a StoreOwnerProfile or ClientProfile
    when a User is created.
    """
    if created:
        if instance.is_store_owner:
            StoreOwnerProfile.objects.create(user=instance)
        elif instance.is_client:
            ClientProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """
    Signal handler to save the StoreOwnerProfile or ClientProfile
    when a User is updated.
    """
    if instance.is_store_owner:
        if hasattr(instance, 'store_owner_profile'):
            instance.store_owner_profile.save()
    elif instance.is_client:
        if hasattr(instance, 'client_profile'):
            instance.client_profile.save()