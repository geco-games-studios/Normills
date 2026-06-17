"""
Management command to flag abandoned carts and send recovery reminders.
Should be run periodically via cron (e.g. every 30 minutes).

Usage:
    python manage.py process_abandoned_carts
"""

from django.core.management.base import BaseCommand
from store.abandoned_cart import flag_abandoned_carts, send_scheduled_reminders


class Command(BaseCommand):
    help = 'Flags abandoned carts and sends scheduled recovery reminders.'

    def handle(self, *args, **options):
        # Step 1: Flag new abandoned carts
        flagged = flag_abandoned_carts()
        self.stdout.write(f'Flagged {flagged} abandoned cart(s).')

        # Step 2: Send due reminders
        sent = send_scheduled_reminders()
        self.stdout.write(f'Sent {sent} reminder(s).')