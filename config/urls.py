from django.contrib import admin
from django.urls import include, path

from chatbots.views_alexa import alexa_ask, alexa_page
from chatbots.views_widget import demo_page, widget_script
from users.views import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("widget.js", widget_script, name="widget-js"),
    path("demo/", demo_page, name="widget-demo"),
    path("alexa/", alexa_page, name="alexa-sim"),
    path("alexa/ask/", alexa_ask, name="alexa-ask"),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("users.urls")),
    path("api/", include("chatbots.urls")),
]
