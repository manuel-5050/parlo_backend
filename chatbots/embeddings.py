import hashlib
import json
import logging
import math
import re
import time
import urllib.error
import urllib.request

from django.conf import settings

from .models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when text could not be turned into embeddings. Messages are safe to show users."""


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


class FakeEmbedder:
    """Free, offline embedder for development and tests.

    Hashes words into a vector, so texts that share words end up close together.
    It is NOT smart (no synonyms) but it lets the whole pipeline run without a key.
    """

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            digest = int(hashlib.md5(word.encode()).hexdigest(), 16)
            sign = 1.0 if (digest >> 100) & 1 else -1.0
            vector[digest % EMBEDDING_DIMENSIONS] += sign
        if not any(vector):
            vector[0] = 1.0
        return _normalize(vector)

    def embed_documents(self, texts: list[str], title: str = "") -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class GeminiEmbedder:
    """Google Gemini embeddings over plain HTTPS (no extra packages needed)."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    BATCH_SIZE = 50
    RETRY_STATUSES = (429, 500, 502, 503, 504)

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_EMBEDDING_MODEL
        if not self.api_key:
            raise EmbeddingError("The embedding service is not configured.")

    def _post(self, method: str, payload: dict) -> dict:
        url = f"{self.BASE_URL}/models/{self.model}:{method}"
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        for attempt in range(4):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                if exc.code in self.RETRY_STATUSES and attempt < 3:
                    time.sleep(2**attempt)
                    continue
                logger.warning("Gemini embeddings returned HTTP %s", exc.code)
                raise EmbeddingError(
                    f"The embedding service returned an error (HTTP {exc.code})."
                ) from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < 3:
                    time.sleep(2**attempt)
                    continue
                raise EmbeddingError("Could not reach the embedding service.") from None
        raise EmbeddingError("The embedding service did not respond.")

    def _request_item(self, text: str, title: str, is_query: bool) -> dict:
        item = {
            "model": f"models/{self.model}",
            "output_dimensionality": EMBEDDING_DIMENSIONS,
        }
        if "embedding-001" in self.model:
            # The older model has a task type field instead of text prefixes.
            item["taskType"] = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
            if title and not is_query:
                item["title"] = title
        else:
            # gemini-embedding-2 expects the task to be written into the text.
            if is_query:
                text = f"task: search result | query: {text}"
            else:
                text = f"title: {title or 'none'} | text: {text}"
        item["content"] = {"parts": [{"text": text}]}
        return item

    def _embed(self, texts: list[str], title: str, is_query: bool) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start : start + self.BATCH_SIZE]
            data = self._post(
                "batchEmbedContents",
                {"requests": [self._request_item(t, title, is_query) for t in batch]},
            )
            embeddings = data.get("embeddings") or []
            if len(embeddings) != len(batch):
                raise EmbeddingError("The embedding service returned an unexpected response.")
            for embedding in embeddings:
                values = embedding.get("values") or []
                if len(values) != EMBEDDING_DIMENSIONS:
                    raise EmbeddingError("The embedding service returned an unexpected size.")
                vectors.append(_normalize(values))
        return vectors

    def embed_documents(self, texts: list[str], title: str = "") -> list[list[float]]:
        return self._embed(texts, title, is_query=False)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "", is_query=True)[0]


def get_embedder():
    backend = settings.EMBEDDING_BACKEND
    if backend == "gemini":
        return GeminiEmbedder()
    if backend == "fake":
        return FakeEmbedder()
    raise EmbeddingError("The embedding service is not configured.")
