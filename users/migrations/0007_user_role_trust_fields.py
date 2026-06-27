from django.db import migrations, models


def backfill_user_roles(apps, schema_editor):
    User = apps.get_model('users', 'User')
    for user in User.objects.all().only('id', 'is_superuser', 'is_staff', 'is_store_owner', 'is_client'):
        if user.is_superuser or user.is_staff:
            role = 'administrator'
        elif user.is_store_owner:
            role = 'merchant'
        else:
            role = 'customer'
        User.objects.filter(pk=user.pk).update(role=role)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_user_profile_picture'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('customer', 'Customer'),
                    ('merchant', 'Merchant'),
                    ('verified_merchant', 'Verified Merchant'),
                    ('delivery_partner', 'Delivery Partner'),
                    ('administrator', 'Administrator'),
                    ('finance_administrator', 'Financial Administrator'),
                    ('moderator', 'Moderator'),
                    ('support_officer', 'Support Officer'),
                ],
                db_index=True,
                default='customer',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='verification_status',
            field=models.CharField(
                choices=[
                    ('unverified', 'Unverified'),
                    ('pending', 'Pending Review'),
                    ('verified', 'Verified'),
                    ('rejected', 'Rejected'),
                ],
                db_index=True,
                default='unverified',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='trust_badges',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill_user_roles, migrations.RunPython.noop),
    ]
