from pgvector.django import CosineDistance

from .embeddings import get_embedder
from .models import Chunk


def search_chunks(bot, query: str, k: int = 5) -> list[Chunk]:
    """The `k` chunks of this bot's knowledge closest in meaning to `query`.

    Always filtered by bot, so one customer's knowledge can never leak into another's.
    Each returned chunk has a `distance` attribute (0 = identical, 2 = opposite).
    """
    vector = get_embedder().embed_query(query)
    return list(
        Chunk.objects.filter(bot=bot)
        .select_related("source")
        .annotate(distance=CosineDistance("embedding", vector))
        .order_by("distance")[:k]
    )
