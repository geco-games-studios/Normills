from django.db import migrations, models


DEFAULT_SOCIAL_LINKS = [
    ('Instagram', 10),
    ('TikTok', 20),
    ('Facebook', 30),
    ('X', 40),
    ('YouTube', 50),
    ('WhatsApp', 60),
]


def seed_social_links(apps, schema_editor):
    SocialLink = apps.get_model('store', 'SocialLink')
    for label, sort_order in DEFAULT_SOCIAL_LINKS:
        SocialLink.objects.get_or_create(
            label=label,
            defaults={'sort_order': sort_order, 'active': False, 'url': ''},
        )


def remove_seed_social_links(apps, schema_editor):
    SocialLink = apps.get_model('store', 'SocialLink')
    SocialLink.objects.filter(label__in=[label for label, _ in DEFAULT_SOCIAL_LINKS], url='').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0021_product_show_selling_fast'),
    ]

    operations = [
        migrations.CreateModel(
            name='NewsletterSubscriber',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SocialLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(max_length=60, unique=True)),
                ('url', models.URLField(blank=True)),
                ('active', models.BooleanField(default=False)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['sort_order', 'label'],
            },
        ),
        migrations.RunPython(seed_social_links, remove_seed_social_links),
    ]
