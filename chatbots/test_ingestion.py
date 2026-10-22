import io
import json
import urllib.error
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from .chunking import split_text
from .embeddings import EMBEDDING_DIMENSIONS, EmbeddingError, FakeEmbedder, GeminiEmbedder
from .models import Bot, Chunk, Source
from .retrieval import search_chunks
from .tasks import process_source

User = get_user_model()

HOURS = "Our shop opens at nine in the morning and closes at six in the evening, Monday to Saturday."
REFUNDS = "Refunds are possible within thirty days if you keep the receipt and the original packaging."
DELIVERY = "Delivery takes two to three working days inside the city and a week to other regions."


class ChunkingTests(SimpleTestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(split_text("Hello there, this is short."), ["Hello there, this is short."])

    def test_empty_text_gives_no_chunks(self):
        self.assertEqual(split_text("   \n\n  "), [])

    def test_paragraphs_are_grouped_up_to_the_limit(self):
        text = "\n\n".join(["a" * 40, "b" * 40, "c" * 40])
        chunks = split_text(text, max_chars=100, overlap=0)
        self.assertEqual(chunks, ["a" * 40 + "\n\n" + "b" * 40, "c" * 40])

    def test_no_chunk_is_longer_than_the_limit(self):
        words = " ".join(f"word{i}" for i in range(2000))
        for max_chars, overlap in [(100, 20), (500, 100), (1000, 150)]:
            for chunk in split_text(words + "\n\n" + words, max_chars=max_chars, overlap=overlap):
                self.assertLessEqual(len(chunk), max_chars)
                self.assertTrue(chunk.strip())

    def test_long_paragraph_is_split_with_overlap_and_loses_nothing(self):
        words = [f"w{i}" for i in range(300)]
        chunks = split_text(" ".join(words), max_chars=200, overlap=40)
        self.assertGreater(len(chunks), 3)
        seen = set(" ".join(chunks).split())
        self.assertEqual(seen, set(words))
        # neighbouring chunks share some words
        self.assertTrue(set(chunks[0].split()) & set(chunks[1].split()))

    def test_text_without_spaces_still_terminates(self):
        chunks = split_text("x" * 5000, max_chars=100, overlap=20)
        self.assertGreater(len(chunks), 40)
        self.assertTrue(all(len(c) <= 100 for c in chunks))


class FakeEmbedderTests(SimpleTestCase):
    def test_vectors_have_the_right_size_and_are_unit_length(self):
        vector = FakeEmbedder().embed_query("opening hours")
        self.assertEqual(len(vector), EMBEDDING_DIMENSIONS)
        self.assertAlmostEqual(sum(v * v for v in vector), 1.0, places=6)

    def test_same_text_same_vector_and_shared_words_are_closer(self):
        e = FakeEmbedder()
        self.assertEqual(e.embed_query("opening hours"), e.embed_query("opening hours"))

        def sim(a, b):
            return sum(x * y for x, y in zip(e.embed_query(a), e.embed_query(b)))

        self.assertGreater(sim("shop opening hours", "opening hours today"), sim("shop opening hours", "refund receipt"))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def gemini_ok(count):
    return FakeResponse(json.dumps({"embeddings": [{"values": [0.5] * EMBEDDING_DIMENSIONS} for _ in range(count)]}).encode())


@override_settings(GEMINI_API_KEY="secret-key-123", GEMINI_EMBEDDING_MODEL="gemini-embedding-2")
class GeminiEmbedderTests(SimpleTestCase):
    def test_document_request_shape_and_normalised_result(self):
        with patch("urllib.request.urlopen", return_value=gemini_ok(2)) as urlopen:
            vectors = GeminiEmbedder().embed_documents(["first", "second"], title="Hours")
        request = urlopen.call_args[0][0]
        self.assertTrue(request.full_url.endswith("/models/gemini-embedding-2:batchEmbedContents"))
        self.assertEqual(request.get_header("X-goog-api-key"), "secret-key-123")
        body = json.loads(request.data)
        self.assertEqual(len(body["requests"]), 2)
        first = body["requests"][0]
        self.assertEqual(first["output_dimensionality"], EMBEDDING_DIMENSIONS)
        self.assertEqual(first["content"]["parts"][0]["text"], "title: Hours | text: first")
        self.assertAlmostEqual(sum(v * v for v in vectors[0]), 1.0, places=6)

    def test_query_uses_the_query_prefix(self):
        with patch("urllib.request.urlopen", return_value=gemini_ok(1)) as urlopen:
            GeminiEmbedder().embed_query("when do you open?")
        body = json.loads(urlopen.call_args[0][0].data)
        self.assertEqual(
            body["requests"][0]["content"]["parts"][0]["text"],
            "task: search result | query: when do you open?",
        )

    @override_settings(GEMINI_EMBEDDING_MODEL="gemini-embedding-001")
    def test_older_model_uses_task_type(self):
        with patch("urllib.request.urlopen", return_value=gemini_ok(1)) as urlopen:
            GeminiEmbedder().embed_documents(["text"], title="T")
        item = json.loads(urlopen.call_args[0][0].data)["requests"][0]
        self.assertEqual(item["taskType"], "RETRIEVAL_DOCUMENT")
        self.assertEqual(item["content"]["parts"][0]["text"], "text")

    def test_large_inputs_are_sent_in_batches(self):
        calls = []

        def fake(request, timeout=None):
            count = len(json.loads(request.data)["requests"])
            calls.append(count)
            return gemini_ok(count)

        with patch("urllib.request.urlopen", side_effect=fake):
            vectors = GeminiEmbedder().embed_documents([f"t{i}" for i in range(120)])
        self.assertEqual(calls, [50, 50, 20])
        self.assertEqual(len(vectors), 120)

    def test_retries_on_rate_limit_then_succeeds(self):
        error = urllib.error.HTTPError("u", 429, "Too Many", {}, io.BytesIO(b"{}"))
        with patch("urllib.request.urlopen", side_effect=[error, gemini_ok(1)]), patch("time.sleep") as sleep:
            vectors = GeminiEmbedder().embed_query("hi")
        self.assertEqual(len(vectors), EMBEDDING_DIMENSIONS)
        sleep.assert_called_once()

    def test_errors_do_not_leak_the_api_key(self):
        error = urllib.error.HTTPError("https://x?key=secret-key-123", 400, "Bad", {}, io.BytesIO(b"{}"))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(EmbeddingError) as ctx:
                GeminiEmbedder().embed_query("hi")
        self.assertNotIn("secret-key-123", str(ctx.exception))
        self.assertIn("400", str(ctx.exception))

    def test_wrong_size_or_count_is_rejected(self):
        bad = FakeResponse(json.dumps({"embeddings": [{"values": [0.1, 0.2]}]}).encode())
        with patch("urllib.request.urlopen", return_value=bad):
            with self.assertRaises(EmbeddingError):
                GeminiEmbedder().embed_query("hi")

    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_is_a_clear_error(self):
        with self.assertRaises(EmbeddingError):
            GeminiEmbedder()


@override_settings(EMBEDDING_BACKEND="fake", CHUNK_MAX_CHARS=120, CHUNK_OVERLAP=20)
class ProcessingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("emmanuel", "e@example.com", "pass12345")
        self.bot = Bot.objects.create(owner=self.user, name="Shop helper")

    def _source(self, content=None, **fields):
        content = content if content is not None else f"{HOURS}\n\n{REFUNDS}\n\n{DELIVERY}"
        return Source.objects.create(bot=self.bot, title="Shop FAQ", content=content, **fields)

    def test_source_becomes_ready_with_chunks(self):
        source = self._source()
        process_source(str(source.id))
        source.refresh_from_db()
        self.assertEqual(source.status, "ready")
        self.assertEqual(source.error, "")
        self.assertEqual(source.chunk_count, Chunk.objects.filter(source=source).count())
        self.assertGreaterEqual(source.chunk_count, 3)

    def test_search_finds_the_right_chunk(self):
        process_source(str(self._source().id))
        top = search_chunks(self.bot, "what time does the shop close in the evening", k=1)[0]
        self.assertIn("closes at six", top.content)
        top = search_chunks(self.bot, "refunds and the receipt", k=1)[0]
        self.assertIn("Refunds", top.content)

    def test_search_never_returns_another_bots_chunks(self):
        other = Bot.objects.create(owner=self.user, name="Other")
        process_source(str(self._source().id))
        secret = Source.objects.create(bot=other, title="s", content="The secret code is swordfish for the shop opening.")
        process_source(str(secret.id))
        results = search_chunks(self.bot, "shop opening secret code swordfish", k=10)
        self.assertTrue(all(chunk.bot_id == self.bot.id for chunk in results))
        self.assertFalse(any("swordfish" in chunk.content for chunk in results))

    def test_processing_twice_does_nothing_the_second_time(self):
        source = self._source()
        process_source(str(source.id))
        count = Chunk.objects.count()
        with patch("chatbots.tasks.get_embedder") as embedder:
            process_source(str(source.id))
        embedder.assert_not_called()
        self.assertEqual(Chunk.objects.count(), count)

    def test_reprocessing_replaces_old_chunks(self):
        source = self._source()
        process_source(str(source.id))
        Source.objects.filter(pk=source.pk).update(status="pending", content=HOURS)
        process_source(str(source.id))
        source.refresh_from_db()
        self.assertEqual(Chunk.objects.filter(source=source).count(), source.chunk_count)
        self.assertEqual(source.chunk_count, 1)

    def test_embedding_failure_marks_failed_with_a_safe_message(self):
        source = self._source()
        with patch("chatbots.tasks.get_embedder") as embedder:
            embedder.return_value.embed_documents.side_effect = EmbeddingError("The embedding service returned an error (HTTP 429).")
            process_source(str(source.id))
        source.refresh_from_db()
        self.assertEqual(source.status, "failed")
        self.assertIn("HTTP 429", source.error)
        self.assertFalse(Chunk.objects.exists())

    def test_unexpected_failure_hides_details(self):
        source = self._source()
        with patch("chatbots.tasks.get_embedder", side_effect=RuntimeError("db password is hunter2")):
            process_source(str(source.id))
        source.refresh_from_db()
        self.assertEqual(source.status, "failed")
        self.assertNotIn("hunter2", source.error)

    def test_a_deleted_source_is_ignored(self):
        process_source("00000000-0000-0000-0000-000000000000")


@override_settings(EMBEDDING_BACKEND="fake", CHUNK_MAX_CHARS=120, CHUNK_OVERLAP=20)
class IngestionApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("emmanuel", "e@example.com", "pass12345")
        self.other = User.objects.create_user("someone", "s@example.com", "pass12345")
        self.bot = Bot.objects.create(owner=self.user, name="Shop helper")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/bots/{self.bot.id}/sources/"

    def test_adding_a_source_queues_processing_after_commit(self):
        with patch("chatbots.views.process_source.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.url, {"title": "FAQ", "content": HOURS}, format="json")
        self.assertEqual(response.status_code, 201)
        delay.assert_called_once_with(response.data["id"])

    def test_full_flow_then_search_through_the_api(self):
        with patch("chatbots.views.process_source.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                created = self.client.post(self.url, {"title": "FAQ", "content": f"{HOURS}\n\n{REFUNDS}"}, format="json")
        process_source(delay.call_args[0][0])
        status = self.client.get(f"{self.url}{created.data['id']}/")
        self.assertEqual(status.data["status"], "ready")
        found = self.client.get(f"/api/bots/{self.bot.id}/search/", {"q": "refund receipt packaging"})
        self.assertEqual(found.status_code, 200)
        self.assertIn("Refunds", found.data[0]["content"])
        self.assertEqual(found.data[0]["source"], "FAQ")

    def test_search_needs_a_question_and_the_right_owner(self):
        self.assertEqual(self.client.get(f"/api/bots/{self.bot.id}/search/").status_code, 400)
        theirs = Bot.objects.create(owner=self.other, name="theirs")
        self.assertEqual(self.client.get(f"/api/bots/{theirs.id}/search/", {"q": "hi"}).status_code, 404)

    def test_reprocess_a_failed_source(self):
        source = Source.objects.create(bot=self.bot, title="s", content=HOURS, status="failed", error="boom")
        with patch("chatbots.views.process_source.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f"{self.url}{source.id}/reprocess/")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "pending")
        delay.assert_called_once_with(str(source.id))

    def test_cannot_reprocess_while_running(self):
        source = Source.objects.create(bot=self.bot, title="s", content=HOURS, status="processing")
        self.assertEqual(self.client.post(f"{self.url}{source.id}/reprocess/").status_code, 409)

    def test_cannot_reprocess_someone_elses_source(self):
        theirs = Bot.objects.create(owner=self.other, name="theirs")
        source = Source.objects.create(bot=theirs, title="s", content=HOURS, status="failed")
        url = f"/api/bots/{theirs.id}/sources/{source.id}/reprocess/"
        self.assertEqual(self.client.post(url).status_code, 404)
