from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Bot

User = get_user_model()


class PublicBotInfoTests(TestCase):
    def setUp(self):
        cache.clear()
        owner = User.objects.create_user("emmanuel", "e@example.com", "pass12345")
        self.bot = Bot.objects.create(
            owner=owner,
            name="Shop helper",
            welcome_message="Welcome to the shop!",
            instructions="SECRET OWNER NOTES",
        )
        self.client = APIClient()

    def _get(self, key=None, **extra):
        return self.client.get(
            "/api/public/bot/", HTTP_X_BOT_KEY=key or self.bot.public_key, **extra
        )

    def test_returns_only_what_the_widget_needs(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"name": "Shop helper", "welcome_message": "Welcome to the shop!"})
        self.assertNotIn("SECRET OWNER NOTES", str(response.content))

    def test_wrong_key_inactive_bot_and_wrong_site_are_refused(self):
        self.assertEqual(self.client.get("/api/public/bot/").status_code, 401)
        self.assertEqual(self._get(key="pk_nope").status_code, 401)
        Bot.objects.filter(pk=self.bot.pk).update(allowed_domains=["example.com"])
        self.assertEqual(self._get(HTTP_ORIGIN="https://example.com").status_code, 200)
        self.assertEqual(self._get(HTTP_ORIGIN="https://evil.com").status_code, 403)
        Bot.objects.filter(pk=self.bot.pk).update(is_active=False, allowed_domains=[])
        self.assertEqual(self._get().status_code, 401)

    def test_browsers_on_other_sites_may_call_it(self):
        response = self._get(HTTP_ORIGIN="https://some-customer-site.com")
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://some-customer-site.com")


class WidgetFileTests(TestCase):
    def test_widget_js_is_served_as_javascript(self):
        response = self.client.get("/widget.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/javascript", response["Content-Type"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        body = response.content.decode()
        self.assertIn("data-bot-key", body)
        self.assertIn("/api/public/chat/", body)

    def test_widget_never_writes_answers_as_html(self):
        body = self.client.get("/widget.js").content.decode()
        self.assertIn("bubble.textContent = text", body)
        self.assertNotIn("bubble.innerHTML", body)


class DemoPageTests(TestCase):
    KEY = "pk_" + "a" * 32

    def test_not_available_when_debug_is_off(self):
        self.assertEqual(self.client.get("/demo/", {"key": self.KEY}).status_code, 404)

    @override_settings(DEBUG=True)
    def test_page_embeds_the_widget_with_the_key(self):
        response = self.client.get("/demo/", {"key": self.KEY})
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'data-bot-key="{self.KEY}"', response.content.decode())

    @override_settings(DEBUG=True)
    def test_bad_or_hostile_keys_are_rejected(self):
        for bad in ["", "abc", '"><script>alert(1)</script>', "pk_short"]:
            self.assertEqual(self.client.get("/demo/", {"key": bad}).status_code, 400)
