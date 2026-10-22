import json
from unittest.mock import patch

from django.test import TestCase, override_settings

KEY = "pk_exampleKeyForTests123"
RESULT = {"answer": "Yes.", "conversation_id": "abc", "passages": [], "trace": []}


def post(client, body):
    return client.post("/alexa/ask/", json.dumps(body), content_type="application/json")


@override_settings(DEBUG=True)
class AlexaSimulatorTests(TestCase):
    def test_page_is_served(self):
        response = self.client.get("/alexa/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Alexa+ simulator", response.content)

    def test_bad_key_and_empty_question_are_rejected(self):
        self.assertEqual(post(self.client, {"key": "nope", "question": "hi"}).status_code, 400)
        self.assertEqual(post(self.client, {"key": KEY, "question": "  "}).status_code, 400)
        self.assertEqual(post(self.client, {"key": KEY, "question": "x" * 501}).status_code, 400)

    def test_success_returns_the_mcp_result(self):
        with patch("chatbots.views_alexa.call_mcp", return_value=RESULT) as call:
            response = post(self.client, {"key": KEY, "question": "refunds?"})
        self.assertEqual(response.json()["answer"], "Yes.")
        self.assertEqual(call.call_args.args[1:], (KEY, "refunds?", None))

    def test_unreachable_server_is_a_502_without_details(self):
        with patch("chatbots.views_alexa.call_mcp", side_effect=OSError("10.0.0.5 refused")):
            response = post(self.client, {"key": KEY, "question": "hi"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("10.0.0.5", response.content.decode())


class AlexaSimulatorOffInProductionTests(TestCase):
    @override_settings(DEBUG=False)
    def test_hidden_when_debug_is_off(self):
        self.assertEqual(self.client.get("/alexa/").status_code, 404)
        self.assertEqual(post(self.client, {"key": KEY, "question": "hi"}).status_code, 404)