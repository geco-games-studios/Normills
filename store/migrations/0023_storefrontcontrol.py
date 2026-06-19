from django.db import migrations, models


def create_default_storefront_control(apps, schema_editor):
    StorefrontControl = apps.get_model('store', 'StorefrontControl')
    StorefrontControl.objects.get_or_create(id=1)


def remove_default_storefront_control(apps, schema_editor):
    StorefrontControl = apps.get_model('store', 'StorefrontControl')
    StorefrontControl.objects.filter(id=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0022_newslettersubscriber_sociallink'),
    ]

    operations = [
        migrations.CreateModel(
            name='StorefrontControl',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('header_mode', models.CharField(choices=[('interactive', 'Interactive menu'), ('banner', 'Single banner')], default='interactive', max_length=20)),
                ('header_banner', models.ImageField(blank=True, upload_to='storefront/banners/')),
                ('new_in_message', models.CharField(default='Fresh styles, latest arrivals, and new products added to the storefront.', max_length=240)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Storefront Control',
                'verbose_name_plural': 'Storefront Controls',
            },
        ),
        migrations.RunPython(create_default_storefront_control, remove_default_storefront_control),
    ]
