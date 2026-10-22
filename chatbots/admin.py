from django.contrib import admin

from .models import Bot, Chunk, Source


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "is_active", "created_at")
    readonly_fields = ("public_key",)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("title", "bot", "kind", "status", "chunk_count", "created_at")
    list_filter = ("status", "kind")


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("bot", "source", "position")
    exclude = ("embedding",)  # 768 numbers per row would make the page unreadable
