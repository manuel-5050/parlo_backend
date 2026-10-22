from urllib.parse import urlparse

from django.conf import settings
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .chat import answer_question
from .embeddings import EmbeddingError
from .llm import LLMError
from .models import Bot, Conversation, Message


def origin_allowed(bot, origin: str) -> bool:
    """Is a website allowed to embed this bot?

    An empty allowed-domains list means any site. Requests with no Origin header
    are not from a browser page on another site, so they are let through.
    """
    if not bot.allowed_domains or not origin:
        return True
    parsed = urlparse(origin)
    host = (parsed.hostname or "").lower()
    netloc = parsed.netloc.lower()
    if not host:
        return False
    for pattern in bot.allowed_domains:
        has_port = ":" in pattern
        target = netloc if has_port else host
        if pattern.startswith("*."):
            if target.endswith(pattern[1:]):
                return True
        elif target == pattern:
            return True
    return False


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(trim_whitespace=True)
    conversation_id = serializers.UUIDField(required=False)

    def validate_message(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Please type a message.")
        if len(value) > settings.CHAT_MAX_MESSAGE_CHARS:
            raise serializers.ValidationError(
                f"Messages can be at most {settings.CHAT_MAX_MESSAGE_CHARS} characters."
            )
        return value


class PublicChatView(APIView):
    """What the website widget calls. No login: the bot's public key identifies the bot."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chat"

    def post(self, request):
        key = request.headers.get("X-Bot-Key", "").strip()
        bot = Bot.objects.filter(public_key=key, is_active=True).first() if key else None
        if bot is None:
            return Response(
                {"detail": "Invalid or inactive bot key."}, status=status.HTTP_401_UNAUTHORIZED
            )
        if not origin_allowed(bot, request.headers.get("Origin", "")):
            return Response(
                {"detail": "This website is not allowed to use this assistant."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["message"]

        # Protects the bot owner from runaway costs.
        start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        used_today = Message.objects.filter(
            conversation__bot=bot, role=Message.Role.USER, created_at__gte=start_of_day
        ).count()
        if used_today >= settings.MAX_MESSAGES_PER_BOT_PER_DAY:
            return Response(
                {"detail": "This assistant has reached its daily limit. Please try again tomorrow."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        conversation = None
        conversation_id = serializer.validated_data.get("conversation_id")
        if conversation_id:
            conversation = Conversation.objects.filter(pk=conversation_id, bot=bot).first()
            if conversation is None:
                return Response(
                    {"detail": "Conversation not found."}, status=status.HTTP_404_NOT_FOUND
                )
            if conversation.messages.count() >= settings.CHAT_MAX_CONVERSATION_MESSAGES:
                return Response(
                    {"detail": "This conversation is too long. Please start a new one."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            conversation, answer, sources = answer_question(bot, conversation, question)
        except (EmbeddingError, LLMError):
            return Response(
                {"detail": "The assistant is temporarily unavailable. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {"conversation_id": str(conversation.id), "answer": answer, "sources": sources}
        )


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "sources", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "created_at", "message_count"]


class ConversationDetailSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "created_at", "messages"]


class OwnerConversationMixin:
    permission_classes = [IsAuthenticated]

    def get_bot(self):
        return get_object_or_404(Bot, pk=self.kwargs["bot_id"], owner=self.request.user)


class ConversationListView(OwnerConversationMixin, generics.ListAPIView):
    """The owner's view of what visitors have been asking."""

    serializer_class = ConversationSerializer

    def get_queryset(self):
        return Conversation.objects.filter(bot=self.get_bot()).annotate(
            message_count=Count("messages")
        )


class ConversationDetailView(OwnerConversationMixin, generics.RetrieveAPIView):
    serializer_class = ConversationDetailSerializer

    def get_queryset(self):
        return Conversation.objects.filter(bot=self.get_bot()).prefetch_related("messages")
