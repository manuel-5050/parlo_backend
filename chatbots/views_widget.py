import html
import re
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Bot
from .views_chat import origin_allowed

WIDGET_FILE = Path(__file__).resolve().parent / "static" / "chatbots" / "widget.js"
KEY_PATTERN = re.compile(r"^pk_[A-Za-z0-9_-]{10,64}$")


class PublicBotInfoView(APIView):
    """What the widget needs to draw itself. Never exposes the owner's instructions."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "widget"

    def get(self, request):
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
        return Response({"name": bot.name, "welcome_message": bot.welcome_message})


def widget_script(request):
    """Serves the embeddable widget at /widget.js."""
    try:
        source = WIDGET_FILE.read_text(encoding="utf-8")
    except OSError:
        raise Http404("Widget file is missing.")
    response = HttpResponse(source, content_type="application/javascript; charset=utf-8")
    response["Cache-Control"] = "public, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


DEMO_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Parlo widget demo</title>
<style>
  body{{font-family:system-ui,sans-serif;margin:0;color:#1f2937;background:#fafaf9}}
  header{{padding:48px 24px;background:#fef3c7;text-align:center}}
  main{{max-width:640px;margin:0 auto;padding:24px}}
  .note{{font-size:13px;color:#6b7280}}
</style>
</head>
<body>
<header><h1>Your customer's website</h1><p>This is a demo page. Your visitors would see the chat bubble in the corner.</p></header>
<main>
  <p>Ask the assistant a question about the knowledge you gave your bot.</p>
  <p class="note">Demo page, only available while DEBUG is on.</p>
</main>
<script src="/widget.js" data-bot-key="{key}" async></script>
</body>
</html>
"""


def demo_page(request):
    """A page to try the widget on: /demo/?key=pk_... (development only)."""
    if not settings.DEBUG:
        raise Http404()
    key = request.GET.get("key", "")
    if not KEY_PATTERN.match(key):
        return HttpResponseBadRequest("Add ?key=YOUR_BOT_PUBLIC_KEY to the address.")
    return HttpResponse(DEMO_PAGE.format(key=html.escape(key, quote=True)))
