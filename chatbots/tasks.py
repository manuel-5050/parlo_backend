import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction

from .chunking import split_text
from .embeddings import EmbeddingError, get_embedder
from .models import Chunk, Source

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """A problem with the source itself. The message is safe to show the owner."""


def _fail(source_id, message: str) -> None:
    Source.objects.filter(pk=source_id).update(status=Source.Status.FAILED, error=message[:300])


@shared_task(ignore_result=True)
def process_source(source_id: str) -> None:
    """Split a source into chunks, embed them, and store them for searching."""
    # Claim the job. If it is not pending (already running or done), do nothing.
    claimed = Source.objects.filter(pk=source_id, status=Source.Status.PENDING).update(
        status=Source.Status.PROCESSING, error=""
    )
    if not claimed:
        return
    source = Source.objects.get(pk=source_id)

    try:
        pieces = split_text(
            source.content,
            max_chars=settings.CHUNK_MAX_CHARS,
            overlap=settings.CHUNK_OVERLAP,
        )
        if not pieces:
            raise IngestionError("This source has no readable text.")
        vectors = get_embedder().embed_documents(pieces, title=source.title)

        with transaction.atomic():
            Chunk.objects.filter(source=source).delete()
            Chunk.objects.bulk_create(
                [
                    Chunk(bot_id=source.bot_id, source=source, position=i, content=text, embedding=vec)
                    for i, (text, vec) in enumerate(zip(pieces, vectors))
                ]
            )
            Source.objects.filter(pk=source.pk).update(
                status=Source.Status.READY, chunk_count=len(pieces), error=""
            )
    except (IngestionError, EmbeddingError) as exc:
        _fail(source_id, str(exc))
    except Exception:
        logger.exception("Processing source %s failed", source_id)
        _fail(source_id, "Something went wrong while processing this source.")
