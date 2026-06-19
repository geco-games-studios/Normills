from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0024_category_new_in_message_storefrontcontrol_today_message'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentInfo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=120)),
                ('number', models.CharField(max_length=40)),
                ('recipient_name', models.CharField(max_length=120)),
                ('active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Payment Info',
                'verbose_name_plural': 'Payment Info',
                'ordering': ['sort_order', 'title'],
            },
        ),
    ]
