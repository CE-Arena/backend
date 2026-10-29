from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from arena.middleware import (
    ResponsePrivacyMiddleware,
    SubmissionLimitMiddleware,
)


class PlayerSecurityTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = SubmissionLimitMiddleware(
            lambda request: HttpResponse("Allowed")
        )

    def attempt(self, path, ip):
        request = self.factory.post(
            path,
            {"test": "value"},
            REMOTE_ADDR=ip,
        )
        return self.middleware(request)

    def verify_limit(self, path, limit, ip):
        for _ in range(limit):
            response = self.attempt(path, ip)
            self.assertEqual(response.status_code, 200)

        response = self.attempt(path, ip)

        self.assertEqual(response.status_code, 429)
        self.assertGreater(
            int(response["Retry-After"]),
            0,
        )

    def test_player_login_throttling(self):
        self.verify_limit(
            "/accounts/login/",
            10,
            "192.0.2.101",
        )

    def test_player_signup_throttling(self):
        self.verify_limit(
            "/accounts/register/",
            5,
            "192.0.2.102",
        )

    def test_admin_login_protection_preserved(self):
        self.verify_limit(
            "/arena-admin/login/",
            10,
            "192.0.2.103",
        )

    def test_tournament_protection_preserved(self):
        self.verify_limit(
            "/tournaments/9/register/",
            30,
            "192.0.2.104",
        )

    def test_different_ips_have_independent_limits(self):
        for _ in range(5):
            self.attempt(
                "/accounts/register/",
                "192.0.2.105",
            )

        blocked = self.attempt(
            "/accounts/register/",
            "192.0.2.105",
        )

        allowed = self.attempt(
            "/accounts/register/",
            "192.0.2.106",
        )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(allowed.status_code, 200)

    def test_login_and_signup_have_separate_limits(self):
        for _ in range(5):
            self.attempt(
                "/accounts/register/",
                "192.0.2.107",
            )

        self.assertEqual(
            self.attempt(
                "/accounts/register/",
                "192.0.2.107",
            ).status_code,
            429,
        )

        self.assertEqual(
            self.attempt(
                "/accounts/login/",
                "192.0.2.107",
            ).status_code,
            200,
        )

    def test_private_pages_disable_caching(self):
        middleware = ResponsePrivacyMiddleware(
            lambda request: HttpResponse("Private")
        )

        paths = [
            "/accounts/login/",
            "/accounts/register/",
            "/accounts/logout/",
            "/dashboard/",
        ]

        for path in paths:
            with self.subTest(path=path):
                request = self.factory.get(path)
                response = middleware(request)

                self.assertIn(
                    "no-store",
                    response["Cache-Control"],
                )

                self.assertIn(
                    "noindex",
                    response["X-Robots-Tag"],
                )
