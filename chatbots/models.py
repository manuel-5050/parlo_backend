import secrets
import uuid

from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField

# Size of one embedding. Must match what the embedding model returns
# (Gemini is asked for 768 values). Changing it later needs a new migration.
EMBEDDING_DIMENSIONS = 768


def generate_public_key():
    """A key the website widget sends so we know which bot a visitor is talking to."""
    return "pk_" + secrets.token_urlsafe(24)


class Bot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bots"
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    # How the bot should behave: tone, what to avoid, what it is for.
    instructions = models.TextField(blank=True)
    welcome_message = models.CharField(
        max_length=300, default="Hi! How can I help you today?"
    )
    public_key = models.CharField(
        max_length=64, unique=True, default=generate_public_key, editable=False
    )
    # Websites allowed to embed this bot, e.g. ["example.com", "*.example.com"].
    allowed_domains = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Source(models.Model):
    """One piece of knowledge given to a bot: pasted text now, files and URLs later."""

    class Kind(models.TextChoices):
        TEXT = "text"
        URL = "url"
        FILE = "file"

    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        READY = "ready"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="sources")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    error = models.CharField(max_length=300, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Chunk(models.Model):
    """A small piece of a source, stored with its embedding so it can be searched."""

    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="chunks")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveIntegerField()
    content = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)

    class Meta:
        ordering = ["source_id", "position"]
        indexes = [
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]


class Conversation(models.Model):
    """One visitor's chat with a bot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="conversations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Conversation {self.id}"


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    # Titles of the knowledge sources an assistant answer was based on.
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
