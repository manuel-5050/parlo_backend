from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .embeddings import EmbeddingError
from .models import Bot, Source
from .retrieval import search_chunks
from .serializers import BotSerializer, SourceSerializer
from .tasks import process_source


class BotViewSet(viewsets.ModelViewSet):
    """Create, list, edit and delete your own bots."""

    serializer_class = BotSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Owners only ever see their own bots.
        return Bot.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        limit = settings.MAX_BOTS_PER_USER
        if Bot.objects.filter(owner=self.request.user).count() >= limit:
            raise PermissionDenied(f"You have reached the limit of {limit} bots.")
        serializer.save(owner=self.request.user)


class BotScopedMixin:
    permission_classes = [IsAuthenticated]
    serializer_class = SourceSerializer

    def get_bot(self):
        return get_object_or_404(Bot, pk=self.kwargs["bot_id"], owner=self.request.user)

    def get_queryset(self):
        return Source.objects.filter(bot=self.get_bot())


class SourceListCreateView(BotScopedMixin, generics.ListCreateAPIView):
    """List a bot's knowledge sources, or add a text source to it."""

    def perform_create(self, serializer):
        bot = self.get_bot()
        limit = settings.MAX_SOURCES_PER_BOT
        if bot.sources.count() >= limit:
            raise PermissionDenied(f"A bot can have at most {limit} sources.")
        source = serializer.save(bot=bot, kind=Source.Kind.TEXT)
        # Start processing only after the row is committed, so the worker can find it.
        transaction.on_commit(lambda: process_source.delay(str(source.id)))


class SourceDetailView(BotScopedMixin, generics.RetrieveDestroyAPIView):
    """Check one source's status, or delete it (its chunks go with it)."""


class SourceReprocessView(BotScopedMixin, generics.GenericAPIView):
    """Run a finished or failed source through processing again."""

    def post(self, request, bot_id, pk):
        source = get_object_or_404(self.get_queryset(), pk=pk)
        if source.status in (Source.Status.PENDING, Source.Status.PROCESSING):
            return Response(
                {"detail": "This source is already being processed."},
                status=status.HTTP_409_CONFLICT,
            )
        source.status = Source.Status.PENDING
        source.error = ""
        source.save(update_fields=["status", "error"])
        transaction.on_commit(lambda: process_source.delay(str(source.id)))
        return Response(self.get_serializer(source).data, status=status.HTTP_202_ACCEPTED)


class BotSearchView(APIView):
    """Let the owner test what a bot would find for a question, before chat exists."""

    permission_classes = [IsAuthenticated]

    def get(self, request, bot_id):
        bot = get_object_or_404(Bot, pk=bot_id, owner=request.user)
        query = request.query_params.get("q", "").strip()
        if not query or len(query) > 500:
            return Response(
                {"detail": "Provide a question in ?q= (1 to 500 characters)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            chunks = search_chunks(bot, query, k=5)
        except EmbeddingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            [
                {
                    "source": chunk.source.title,
                    "content": chunk.content,
                    "distance": round(float(chunk.distance), 4),
                }
                for chunk in chunks
            ]
        )
