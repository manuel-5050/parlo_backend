from django.apps import AppConfig


class ChatbotsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "chatbots"

    def ready(self):
        from corsheaders.signals import check_request_enabled

        def allow_public_api(sender, request, **kwargs):
            # The embeddable widget runs on other people's websites, so the public
            # chat endpoint must accept browser requests from any origin. The bot's
            # own allowed-domains list is checked inside the view.
            return request.path.startswith("/api/public/")

        check_request_enabled.connect(allow_public_api, weak=False)
