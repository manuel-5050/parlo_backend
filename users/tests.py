from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()

GOOD = {"username": "emmanuel", "email": "Emmanuel@Example.com", "password": "S3cure-pass-phrase"}


class AuthTests(TestCase):
    def setUp(self):
        cache.clear()  # reset the throttle counters between tests
        self.client = APIClient()

    def _signup(self, **overrides):
        return self.client.post("/api/auth/signup/", {**GOOD, **overrides}, format="json")

    def test_health_is_open(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ok")

    def test_signup_returns_tokens_and_hides_password(self):
        response = self._signup()
        self.assertEqual(response.status_code, 201)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], "emmanuel@example.com")
        self.assertNotIn("password", response.data["user"])
        self.assertTrue(User.objects.get(username="emmanuel").check_password(GOOD["password"]))

    def test_signup_token_works_on_me(self):
        access = self._signup().data["access"]
        response = self.client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "emmanuel")

    def test_duplicate_username_rejected_case_insensitively(self):
        self._signup()
        response = self._signup(username="EMMANUEL", email="other@example.com")
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.data)

    def test_duplicate_email_rejected_case_insensitively(self):
        self._signup()
        response = self._signup(username="someoneelse", email="EMMANUEL@example.com")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_weak_password_rejected(self):
        response = self._signup(password="12345678")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_invalid_email_rejected(self):
        self.assertEqual(self._signup(email="not-an-email").status_code, 400)

    def test_signup_is_throttled(self):
        statuses = [
            self._signup(username=f"user{i}", email=f"user{i}@example.com").status_code
            for i in range(8)
        ]
        self.assertIn(429, statuses)

    def test_login_and_refresh(self):
        self._signup()
        login = self.client.post(
            "/api/auth/token/",
            {"username": "emmanuel", "password": GOOD["password"]},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        refresh = self.client.post(
            "/api/auth/token/refresh/", {"refresh": login.data["refresh"]}, format="json"
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertIn("access", refresh.data)

    def test_wrong_password_rejected(self):
        self._signup()
        response = self.client.post(
            "/api/auth/token/", {"username": "emmanuel", "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_me_requires_login(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
