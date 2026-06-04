from django.core.management.base import BaseCommand
from store.ml import train_recommender


class Command(BaseCommand):
    help = 'Train the ecommerce recommender model using bot conversations and product metadata.'

    def handle(self, *args, **options):
        model_path = train_recommender()
        if model_path:
            self.stdout.write(self.style.SUCCESS(f'Recommender trained and saved to: {model_path}'))
        else:
            self.stdout.write(self.style.WARNING('No available data to train the recommender.'))
