import re

from django.conf import settings
from rest_framework import serializers

from .models import Bot, Source

DOMAIN_PATTERN = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?$")


class BotSerializer(serializers.ModelSerializer):
    source_count = serializers.SerializerMethodField()

    class Meta:
        model = Bot
        fields = [
            "id",
            "name",
            "description",
            "instructions",
            "welcome_message",
            "public_key",
            "allowed_domains",
            "is_active",
            "source_count",
            "created_at",
        ]
        read_only_fields = ["id", "public_key", "source_count", "created_at"]

    def get_source_count(self, obj):
        return obj.sources.count()

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("The name cannot be empty.")
        return value

    def validate_instructions(self, value):
        if len(value) > 4000:
            raise serializers.ValidationError("Instructions must be at most 4000 characters.")
        return value

    def validate_allowed_domains(self, value):
        if not isinstance(value, list) or len(value) > 20:
            raise serializers.ValidationError("Provide a list of at most 20 domains.")
        cleaned = []
        for item in value:
            domain = str(item).strip().lower()
            if not DOMAIN_PATTERN.match(domain):
                raise serializers.ValidationError(
                    f"'{item}' is not a valid domain. Use names like example.com or *.example.com."
                )
            if domain not in cleaned:
                cleaned.append(domain)
        return cleaned


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = [
            "id",
            "kind",
            "title",
            "content",
            "status",
            "error",
            "chunk_count",
            "created_at",
        ]
        read_only_fields = ["id", "kind", "status", "error", "chunk_count", "created_at"]
        # The text can be long, so it is accepted on create but not sent back in lists.
        extra_kwargs = {"content": {"write_only": True}}

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("The title cannot be empty.")
        return value

    def validate_content(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError("The text is too short to be useful.")
        if len(value) > settings.MAX_SOURCE_CHARS:
            raise serializers.ValidationError(
                f"The text must be at most {settings.MAX_SOURCE_CHARS} characters."
            )
        return value
