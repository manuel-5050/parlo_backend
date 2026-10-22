from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from pgvector.django import CosineDistance
from rest_framework.test import APIClient

from .models import EMBEDDING_DIMENSIONS, Bot, Chunk, Source

User = get_user_model()

TEXT = "Our shop opens at 9am and closes at 6pm, Monday to Saturday."


def vec(first, second=0.0):
    """A test embedding: two meaningful numbers and zeros for the rest."""
    return [first, second] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


class BotApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("emmanuel", "e@example.com", "pass12345")
        self.other = User.objects.create_user("someone", "s@example.com", "pass12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _create_bot(self, **body):
        body.setdefault("name", "Shop helper")
        return self.client.post("/api/bots/", body, format="json")

    def test_requires_login(self):
        self.assertEqual(APIClient().get("/api/bots/").status_code, 401)

    def test_create_bot_gets_a_public_key(self):
        response = self._create_bot(allowed_domains=["Example.com", "*.example.com", "example.com"])
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["public_key"].startswith("pk_"))
        self.assertEqual(response.data["allowed_domains"], ["example.com", "*.example.com"])
        self.assertEqual(Bot.objects.get().owner, self.user)

    def test_public_keys_are_unique(self):
        first = self._create_bot().data["public_key"]
        second = self._create_bot().data["public_key"]
        self.assertNotEqual(first, second)

    def test_public_key_cannot_be_set_by_the_client(self):
        response = self._create_bot(public_key="pk_chosen")
        self.assertNotEqual(response.data["public_key"], "pk_chosen")

    def test_bad_domain_rejected(self):
        for bad in ["https://example.com", "exa mple.com", "example.com/path"]:
            self.assertEqual(self._create_bot(allowed_domains=[bad]).status_code, 400)

    def test_empty_name_rejected(self):
        self.assertEqual(self._create_bot(name="   ").status_code, 400)

    @override_settings(MAX_BOTS_PER_USER=2)
    def test_bot_limit(self):
        self._create_bot()
        self._create_bot()
        self.assertEqual(self._create_bot().status_code, 403)

    def test_users_only_see_their_own_bots(self):
        mine = Bot.objects.create(owner=self.user, name="mine")
        theirs = Bot.objects.create(owner=self.other, name="theirs")
        listing = self.client.get("/api/bots/")
        self.assertEqual([b["id"] for b in listing.data], [str(mine.id)])
        self.assertEqual(self.client.get(f"/api/bots/{theirs.id}/").status_code, 404)
        self.assertEqual(
            self.client.patch(f"/api/bots/{theirs.id}/", {"name": "x"}, format="json").status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"/api/bots/{theirs.id}/").status_code, 404)

    def test_update_and_delete_own_bot(self):
        bot_id = self._create_bot().data["id"]
        patched = self.client.patch(
            f"/api/bots/{bot_id}/", {"instructions": "Be brief."}, format="json"
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data["instructions"], "Be brief.")
        self.assertEqual(self.client.delete(f"/api/bots/{bot_id}/").status_code, 204)
        self.assertFalse(Bot.objects.exists())


class SourceApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("emmanuel", "e@example.com", "pass12345")
        self.other = User.objects.create_user("someone", "s@example.com", "pass12345")
        self.bot = Bot.objects.create(owner=self.user, name="Shop helper")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/bots/{self.bot.id}/sources/"

    def test_add_text_source(self):
        response = self.client.post(self.url, {"title": "Opening hours", "content": TEXT}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["kind"], "text")
        self.assertEqual(response.data["status"], "pending")
        self.assertNotIn("content", response.data)
        self.assertEqual(Source.objects.get().bot, self.bot)

    def test_client_cannot_set_status_or_kind(self):
        response = self.client.post(
            self.url,
            {"title": "x", "content": TEXT, "status": "ready", "kind": "url"},
            format="json",
        )
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["kind"], "text")

    def test_too_short_and_too_long_rejected(self):
        short = self.client.post(self.url, {"title": "x", "content": "hi"}, format="json")
        self.assertEqual(short.status_code, 400)
        with override_settings(MAX_SOURCE_CHARS=20):
            long = self.client.post(self.url, {"title": "x", "content": TEXT}, format="json")
        self.assertEqual(long.status_code, 400)

    @override_settings(MAX_SOURCES_PER_BOT=1)
    def test_source_limit(self):
        self.client.post(self.url, {"title": "a", "content": TEXT}, format="json")
        again = self.client.post(self.url, {"title": "b", "content": TEXT}, format="json")
        self.assertEqual(again.status_code, 403)

    def test_cannot_touch_another_users_bot(self):
        theirs = Bot.objects.create(owner=self.other, name="theirs")
        url = f"/api/bots/{theirs.id}/sources/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.post(url, {"title": "x", "content": TEXT}, format="json").status_code, 404
        )

    def test_source_must_belong_to_the_bot_in_the_url(self):
        other_bot = Bot.objects.create(owner=self.user, name="second")
        source = Source.objects.create(bot=other_bot, title="s", content=TEXT)
        wrong = f"/api/bots/{self.bot.id}/sources/{source.id}/"
        self.assertEqual(self.client.get(wrong).status_code, 404)

    def test_delete_source_removes_its_chunks(self):
        source = Source.objects.create(bot=self.bot, title="s", content=TEXT)
        Chunk.objects.create(bot=self.bot, source=source, position=0, content="a", embedding=vec(1))
        response = self.client.delete(f"{self.url}{source.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Chunk.objects.exists())

    def test_deleting_a_bot_removes_everything(self):
        source = Source.objects.create(bot=self.bot, title="s", content=TEXT)
        Chunk.objects.create(bot=self.bot, source=source, position=0, content="a", embedding=vec(1))
        self.bot.delete()
        self.assertFalse(Source.objects.exists())
        self.assertFalse(Chunk.objects.exists())


class VectorSearchTests(TestCase):
    """Proves pgvector works: the closest meaning comes back first, per bot."""

    def test_nearest_chunk_first_and_scoped_to_one_bot(self):
        owner = User.objects.create_user("emmanuel", "e@example.com", "pass12345")
        bot = Bot.objects.create(owner=owner, name="a")
        other_bot = Bot.objects.create(owner=owner, name="b")
        source = Source.objects.create(bot=bot, title="s", content=TEXT)
        other_source = Source.objects.create(bot=other_bot, title="s", content=TEXT)
        Chunk.objects.create(bot=bot, source=source, position=0, content="hours", embedding=vec(1, 0))
        Chunk.objects.create(bot=bot, source=source, position=1, content="prices", embedding=vec(0, 1))
        Chunk.objects.create(
            bot=other_bot, source=other_source, position=0, content="secret", embedding=vec(1, 0)
        )

        results = list(
            Chunk.objects.filter(bot=bot)
            .order_by(CosineDistance("embedding", vec(0.9, 0.1)))
            .values_list("content", flat=True)
        )
        self.assertEqual(results, ["hours", "prices"])
