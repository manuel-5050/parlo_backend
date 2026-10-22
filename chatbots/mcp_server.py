"""Parlo as an MCP server (Streamable HTTP), for assistants such as Alexa+.

One connection is one business: the caller sends the bot's key as a bearer token
(`Authorization: Bearer pk_...`) and every tool works on that bot's knowledge only.

Tools:
  search_knowledge          fast; returns the matching passages so the calling
                            assistant can phrase the reply itself (best for voice)
  ask_business_assistant    slower; returns a finished answer written by Parlo's bot
  get_business_info         who the bot speaks for and what it knows about

Run it with:  python manage.py run_mcp_server
"""
import json
import logging
import time
from collections import defaultdict, deque
from contextvars import ContextVar

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.utils import timezone
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .chat import answer_question
from .embeddings import EmbeddingError
from .llm import LLMError
from .models import Bot, Conversation, Message, Source
from .retrieval import search_chunks

logger = logging.getLogger(__name__)

# The business the current request is for. Set by the auth middleware below.
current_bot: ContextVar = ContextVar("parlo_current_bot", default=None)

MAX_QUERY_CHARS = 500
MAX_PASSAGE_CHARS = 800

INSTRUCTIONS = (
    "Parlo gives you the knowledge of one business. Use search_knowledge to look up facts "
    "(opening hours, prices, policies, products) and answer in your own words using only "
    "what it returns. If it returns nothing relevant, say you do not know. "
    "ask_business_assistant returns a ready-made answer but is slower."
)


def run_sync(function, *args, **kwargs):
    """Run blocking code (database, network) off the event loop with a clean DB connection."""

    def call():
        # Tests run everything on one thread inside a transaction; do not close that connection.
        clean = not settings.MCP_THREAD_SENSITIVE
        if clean:
            close_old_connections()
        try:
            return function(*args, **kwargs)
        finally:
            if clean:
                close_old_connections()

    return sync_to_async(call, thread_sensitive=settings.MCP_THREAD_SENSITIVE)()


class RateLimiter:
    """A small in-memory sliding window, per business. Fine for one server process."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self.hits = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


limiter = RateLimiter(limit=30)


def _bot_or_error() -> Bot:
    bot = current_bot.get()
    if bot is None:
        raise ToolError("Not authenticated.")
    limiter.limit = settings.MCP_RATE_PER_MINUTE
    if not limiter.allow(str(bot.id)):
        raise ToolError("Too many requests. Please try again in a moment.")
    return bot


def _clean_query(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ToolError("Please provide a question.")
    if len(text) > MAX_QUERY_CHARS:
        raise ToolError(f"The question must be at most {MAX_QUERY_CHARS} characters.")
    return text


def _search(bot: Bot, query: str, k: int):
    try:
        chunks = search_chunks(bot, query, k=k)
    except EmbeddingError:
        raise ToolError("The knowledge search is temporarily unavailable.") from None
    return [
        {"source": chunk.source.title, "text": chunk.content[:MAX_PASSAGE_CHARS]}
        for chunk in chunks
    ]


def _info(bot: Bot):
    topics = list(
        Source.objects.filter(bot=bot, status=Source.Status.READY)
        .order_by("title")
        .values_list("title", flat=True)[:20]
    )
    return {"business": bot.name, "greeting": bot.welcome_message, "topics": topics}


def _ask(bot: Bot, question: str, conversation_id):
    start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = Message.objects.filter(
        conversation__bot=bot, role=Message.Role.USER, created_at__gte=start_of_day
    ).count()
    if used_today >= settings.MAX_MESSAGES_PER_BOT_PER_DAY:
        raise ToolError("This assistant has reached its daily limit. Please try again tomorrow.")

    conversation = None
    if conversation_id:
        try:
            conversation = Conversation.objects.filter(pk=conversation_id, bot=bot).first()
        except (ValueError, TypeError, ValidationError):
            conversation = None
        if conversation is None:
            raise ToolError("Conversation not found. Start a new one by leaving conversation_id empty.")
        if conversation.messages.count() >= settings.CHAT_MAX_CONVERSATION_MESSAGES:
            raise ToolError("This conversation is too long. Please start a new one.")
    try:
        conversation, answer, sources = answer_question(bot, conversation, question)
    except (EmbeddingError, LLMError):
        raise ToolError("The assistant is temporarily unavailable. Please try again.") from None
    return {"answer": answer, "sources": sources, "conversation_id": str(conversation.id)}


def build_server() -> MCPServer:
    server = MCPServer("Parlo", instructions=INSTRUCTIONS)

    @server.tool()
    async def search_knowledge(query: str, max_results: int = 3) -> dict:
        """Look up facts in this business's own knowledge (opening hours, prices, policies,
        products, delivery, contact details). Returns the most relevant passages with the
        document each came from. Answer the user using only these passages. If the list is
        empty or not relevant, say you do not have that information."""
        bot = _bot_or_error()
        query = _clean_query(query)
        k = max(1, min(int(max_results), 5))
        results = await run_sync(_search, bot, query, k)
        if not results:
            return {"results": [], "message": "No information was found for that question."}
        return {"results": results}

    @server.tool()
    async def ask_business_assistant(question: str, conversation_id: str | None = None) -> dict:
        """Ask the business's own AI assistant a question and get a finished answer based on
        its knowledge. Slower than search_knowledge (a few seconds). Pass the returned
        conversation_id back to ask a follow-up question in the same conversation."""
        bot = _bot_or_error()
        question = _clean_query(question)
        return await run_sync(_ask, bot, question, conversation_id)

    @server.tool()
    async def get_business_info() -> dict:
        """Say which business this assistant speaks for, its greeting, and the topics it
        has knowledge about."""
        bot = _bot_or_error()
        return await run_sync(_info, bot)

    return server


def _find_bot(token: str):
    return Bot.objects.filter(public_key=token, is_active=True).first()


class BotKeyAuthMiddleware:
    """Pure ASGI middleware: only requests with a valid bot key get through."""

    def __init__(self, app):
        self.app = app

    async def _reply(self, send, status, payload):
        body = json.dumps(payload).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/health":
            await self._reply(send, 200, {"status": "ok", "service": "parlo-mcp"})
            return

        headers = {name.lower(): value for name, value in scope["headers"]}
        header = headers.get(b"authorization", b"").decode("latin-1")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        bot = await run_sync(_find_bot, token) if token else None
        if bot is None:
            # No WWW-Authenticate header, as Alexa+ asks for.
            await self._reply(
                send, 401, {"error": "unauthorized", "detail": "Missing or invalid bearer token."}
            )
            return

        marker = current_bot.set(bot)
        try:
            await self.app(scope, receive, send)
        finally:
            current_bot.reset(marker)


def create_app(host: str = "127.0.0.1"):
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.MCP_ALLOWED_HOSTS,
        allowed_origins=settings.MCP_ALLOWED_ORIGINS,
    )
    app = build_server().streamable_http_app(
        stateless_http=True,  # every request carries its own bearer token, so no sessions
        json_response=True,
        transport_security=security,
        host=host,
    )
    return BotKeyAuthMiddleware(app)