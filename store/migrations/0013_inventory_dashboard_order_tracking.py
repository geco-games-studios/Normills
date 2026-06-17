from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def normalize_order_statuses(apps, schema_editor):
    Order = apps.get_model('store', 'Order')
    Order.objects.filter(status='processing').update(status='packing')
    Order.objects.filter(status='shipped').update(status='dispatched')


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('store', '0012_wishlistitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='low_stock_threshold',
            field=models.PositiveIntegerField(default=5),
        ),
        migrations.AddField(
            model_name='product',
            name='offline_stock',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_method',
            field=models.CharField(choices=[('delivery', 'Delivery'), ('pickup', 'Pickup')], default='delivery', max_length=20),
        ),
        migrations.AddField(
            model_name='order',
            name='notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='stock_deducted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('payment_awaiting', 'Payment awaiting confirmation'), ('paid', 'Paid'), ('packing', 'Packing'), ('dispatched', 'Dispatched'), ('delivered', 'Delivered'), ('cancelled', 'Cancelled'), ('refunded', 'Refunded')], default='pending', max_length=20),
        ),
        migrations.CreateModel(
            name='StockAdjustment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_online_stock', models.PositiveIntegerField(default=0)),
                ('new_online_stock', models.PositiveIntegerField(default=0)),
                ('previous_offline_stock', models.PositiveIntegerField(default=0)),
                ('new_offline_stock', models.PositiveIntegerField(default=0)),
                ('reason', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stock_adjustments', to='store.product')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.RunPython(normalize_order_statuses, migrations.RunPython.noop),
    ]
