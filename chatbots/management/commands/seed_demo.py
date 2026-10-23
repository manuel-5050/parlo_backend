from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from chatbots.models import Bot, Source
from chatbots.tasks import process_source

KNOWLEDGE = """Opening hours
Sunrise Shop opens at 9am and closes at 6pm, Monday to Saturday. We are closed on Sundays and public holidays.

Refunds
Refunds are possible within thirty days of purchase if you keep the receipt and the original packaging. Refunds are paid back the way you paid. Sale items can only be exchanged.

Delivery
Delivery takes two to three working days inside the city and about a week to other regions. Delivery inside the city is free for orders above 200 cedis.

Payment
We accept mobile money, bank cards and cash. We do not accept cheques.

Contact
Call us on 020 000 0000 or visit us at 12 Market Street, Kumasi."""


class Command(BaseCommand):
    help = "Create a demo admin user and a demo business with knowledge, and print its bot key."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="ParloDemo2026!", help="password for the demo_admin user")

    def handle(self, *args, **options):
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username="demo_admin", defaults={"email": "demo-admin@parlo.local"}
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password(options["password"])
        user.save()

        bot, _ = Bot.objects.get_or_create(
            owner=user,
            name="Sunrise Shop",
            defaults={
                "welcome_message": "Hi! Ask me about opening hours, refunds, delivery or payments.",
                "instructions": "You are the friendly assistant of Sunrise Shop. Keep answers short and clear.",
            },
        )
        source, _ = Source.objects.get_or_create(
            bot=bot, title="Shop FAQ", defaults={"content": KNOWLEDGE}
        )
        if source.status != Source.Status.READY:
            process_source(str(source.id))
            source.refresh_from_db()

        self.stdout.write(f"Knowledge status: {source.status}")
        self.stdout.write(f"Bot key:          {bot.public_key}")
        self.stdout.write(f"Admin login:      demo_admin / {options['password']}")
        self.stdout.write(f"Alexa+ simulator: http://localhost:8001/alexa/?key={bot.public_key}")
        self.stdout.write(f"Widget demo:      http://localhost:8001/demo/?key={bot.public_key}")
        self.stdout.write(f"MCP endpoint:     http://localhost:8002/mcp  (Authorization: Bearer {bot.public_key})")