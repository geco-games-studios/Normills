from django.db import migrations, models


def enable_existing_low_stock_badges(apps, schema_editor):
    Product = apps.get_model('store', 'Product')
    Product.objects.filter(stock__lt=5).update(show_selling_fast=True)


def clear_selling_fast_badges(apps, schema_editor):
    Product = apps.get_model('store', 'Product')
    Product.objects.update(show_selling_fast=False)


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0020_cashiercontact'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='show_selling_fast',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(enable_existing_low_stock_badges, clear_selling_fast_badges),
    ]
