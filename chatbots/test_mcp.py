import json
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from mcp.server.mcpserver.exceptions import ToolError

from . import mcp_server
from .embeddings import EmbeddingError
from .models import Bot, Message, Source
from .tasks import process_source

User = get_user_model()

HOURS = "Our shop opens at nine in the morning and closes at six in the evening, Monday to Saturday."
REFUNDS = "Refunds are possible within thirty days if you keep the receipt and the original packaging."


async def call_asgi(app, path="/mcp", headers=None):
    """Send one HTTP request straight to an ASGI app and return (status, body)."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path, "method": "POST", "headers": headers or []}
    await app(scope, receive, send)
    status = sent[0]["status"]
    body = b"".join(m.get("body", b"") for m in sent[1:])
    return status, body


@override_settings(MCP_THREAD_SENSITIVE=True)
class McpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("emmanuel", "e@example.com", "pass12345")
        self.bot = Bot.objects.create(owner=self.user, name="Sunrise Shop", welcome_message="Hi!")
        source = Source.objects.create(bot=self.bot, title="Shop FAQ", content=f"{HOURS}\n\n{REFUNDS}")
        process_source(str(source.id))
        mcp_server.limiter.hits.clear()
        self.seen = []

        async def inner(scope, receive, send):
            self.seen.append(mcp_server.current_bot.get())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        self.app = mcp_server.BotKeyAuthMiddleware(inner)

    def _auth(self, token):
        return [(b"authorization", f"Bearer {token}".encode())]

    def test_health_needs_no_key(self):
        status, body = async_to_sync(call_asgi)(self.app, path="/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_missing_or_wrong_key_is_401(self):
        for headers in ([], self._auth("pk_wrong"), [(b"authorization", b"Basic abc")]):
            status, _ = async_to_sync(call_asgi)(self.app, headers=headers)
            self.assertEqual(status, 401)
        self.assertEqual(self.seen, [])

    def test_inactive_bot_is_401(self):
        self.bot.is_active = False
        self.bot.save()
        status, _ = async_to_sync(call_asgi)(self.app, headers=self._auth(self.bot.public_key))
        self.assertEqual(status, 401)

    def test_valid_key_sets_the_bot_for_the_request_only(self):
        status, _ = async_to_sync(call_asgi)(self.app, headers=self._auth(self.bot.public_key))
        self.assertEqual(status, 200)
        self.assertEqual(self.seen, [self.bot])
        self.assertIsNone(mcp_server.current_bot.get())

    def test_search_returns_passages_with_source(self):
        results = mcp_server._search(self.bot, "when does the shop close", 3)
        self.assertEqual(results[0]["source"], "Shop FAQ")
        self.assertIn("six in the evening", results[0]["text"])

    def test_search_never_returns_another_bots_knowledge(self):
        other = Bot.objects.create(owner=self.user, name="Other")
        self.assertEqual(mcp_server._search(other, "refund", 3), [])

    def test_search_embedding_failure_is_a_clean_tool_error(self):
        with patch.object(mcp_server, "search_chunks", side_effect=EmbeddingError("secret detail")):
            with self.assertRaises(ToolError) as ctx:
                mcp_server._search(self.bot, "hours", 3)
        self.assertNotIn("secret", str(ctx.exception))

    def test_info(self):
        info = mcp_server._info(self.bot)
        self.assertEqual(info["business"], "Sunrise Shop")
        self.assertEqual(info["topics"], ["Shop FAQ"])

    def test_ask_answers_and_continues_a_conversation(self):
        first = mcp_server._ask(self.bot, "when does the shop close", None)
        self.assertEqual(first["sources"], ["Shop FAQ"])
        second = mcp_server._ask(self.bot, "and refunds?", first["conversation_id"])
        self.assertEqual(second["conversation_id"], first["conversation_id"])

    def test_ask_rejects_a_conversation_of_another_bot(self):
        other = Bot.objects.create(owner=self.user, name="Other")
        theirs = mcp_server._ask(other, "hello", None)
        with self.assertRaises(ToolError):
            mcp_server._ask(self.bot, "hello", theirs["conversation_id"])
        with self.assertRaises(ToolError):
            mcp_server._ask(self.bot, "hello", "not-a-uuid")

    @override_settings(MAX_MESSAGES_PER_BOT_PER_DAY=1)
    def test_ask_respects_the_daily_cap(self):
        mcp_server._ask(self.bot, "hello", None)
        with self.assertRaises(ToolError):
            mcp_server._ask(self.bot, "hello again", None)
        self.assertEqual(Message.objects.filter(role="user").count(), 1)

    def test_query_validation(self):
        with self.assertRaises(ToolError):
            mcp_server._clean_query("   ")
        with self.assertRaises(ToolError):
            mcp_server._clean_query("x" * 501)
        self.assertEqual(mcp_server._clean_query("  hi  "), "hi")


class RateLimiterTests(SimpleTestCase):
    def test_blocks_after_the_limit_and_keeps_businesses_apart(self):
        limiter = mcp_server.RateLimiter(limit=2)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))

    def test_window_expires(self):
        limiter = mcp_server.RateLimiter(limit=1, window=0.0)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))