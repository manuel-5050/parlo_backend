import json
import logging
import re
import time
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The language model could not produce an answer. Messages are safe to show."""


class FakeLLM:
    """Free offline stand-in so the whole chat flow works without any key."""

    def generate(self, system: str, messages: list[dict]) -> str:
        last = messages[-1]["content"]
        match = re.search(r"<context>\s*(.*?)\s*</context>", last, re.S)
        snippet = (match.group(1) if match else "")[:300]
        if snippet:
            return f"(demo answer, no AI model connected) {snippet}"
        return "(demo answer, no AI model connected) I don't have that information."


class GeminiLLM:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    RETRY_STATUSES = (429, 500, 502, 503, 504)

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_CHAT_MODEL
        if not self.api_key:
            raise LLMError("The assistant is not configured.")

    def _post(self, payload: dict) -> dict:
        url = f"{self.BASE_URL}/models/{self.model}:generateContent"
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        for attempt in range(3):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                if exc.code in self.RETRY_STATUSES and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                logger.warning("Gemini chat returned HTTP %s", exc.code)
                raise LLMError(f"The AI service returned an error (HTTP {exc.code}).") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise LLMError("Could not reach the AI service.") from None
        raise LLMError("The AI service did not respond.")

    def generate(self, system: str, messages: list[dict]) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "user" if m["role"] == "user" else "model",
                    "parts": [{"text": m["content"]}],
                }
                for m in messages
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": settings.CHAT_MAX_OUTPUT_TOKENS,
            },
        }
        data = self._post(payload)
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("The AI service declined to answer.")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise LLMError("The AI service returned an empty answer.")
        return text


def get_llm():
    backend = settings.LLM_BACKEND
    if backend == "gemini":
        return GeminiLLM()
    if backend == "fake":
        return FakeLLM()
    raise LLMError("The assistant is not configured.")
