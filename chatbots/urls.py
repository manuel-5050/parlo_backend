from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BotSearchView,
    BotViewSet,
    SourceDetailView,
    SourceListCreateView,
    SourceReprocessView,
)
from .views_chat import ConversationDetailView, ConversationListView, PublicChatView
from .views_widget import PublicBotInfoView

router = DefaultRouter()
router.register("bots", BotViewSet, basename="bot")

urlpatterns = [
    path("bots/<uuid:bot_id>/sources/", SourceListCreateView.as_view(), name="source-list"),
    path(
        "bots/<uuid:bot_id>/sources/<uuid:pk>/",
        SourceDetailView.as_view(),
        name="source-detail",
    ),
    path(
        "bots/<uuid:bot_id>/sources/<uuid:pk>/reprocess/",
        SourceReprocessView.as_view(),
        name="source-reprocess",
    ),
    path("bots/<uuid:bot_id>/search/", BotSearchView.as_view(), name="bot-search"),
    path("bots/<uuid:bot_id>/conversations/", ConversationListView.as_view(), name="conversation-list"),
    path(
        "bots/<uuid:bot_id>/conversations/<uuid:pk>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path("public/bot/", PublicBotInfoView.as_view(), name="public-bot"),
    path("public/chat/", PublicChatView.as_view(), name="public-chat"),
    path("", include(router.urls)),
]
