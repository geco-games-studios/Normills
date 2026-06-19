from django.db import migrations, models


DEFAULT_MESSAGE = 'Fresh styles, latest arrivals, and new products added to the storefront.'


def seed_messages(apps, schema_editor):
    Category = apps.get_model('store', 'Category')
    StorefrontControl = apps.get_model('store', 'StorefrontControl')
    StorefrontControl.objects.update(today_new_in_message=DEFAULT_MESSAGE)
    for category in Category.objects.filter(new_in_message=''):
        category.new_in_message = f"Fresh arrivals selected from {category.name}."
        category.save(update_fields=['new_in_message'])


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0023_storefrontcontrol'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='new_in_message',
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name='storefrontcontrol',
            name='today_new_in_message',
            field=models.CharField(default=DEFAULT_MESSAGE, max_length=240),
        ),
        migrations.RunPython(seed_messages, migrations.RunPython.noop),
    ]
