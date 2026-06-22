import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import email_service


class _FakeResponse:
    status = 200

    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


class ResendEmailServiceTests(unittest.TestCase):
    def test_send_email_uses_resend_sender_and_reply_to(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse({"id": "email_123"})

        with (
            patch.dict(
                os.environ,
                {
                    "RESEND_API_KEY": "re_secret_test_key",
                    "EMAIL_FROM": "TIS <info@tisplatform.com>",
                    "EMAIL_REPLY_TO": "support@tisplatform.com",
                    "RESEND_TIMEOUT_SECONDS": "9",
                },
                clear=True,
            ),
            patch.object(email_service, "urlopen", side_effect=fake_urlopen),
        ):
            message_id = email_service.send_email(
                to="owner@example.com",
                subject="Verify email",
                text="Verification body",
                html="<strong>Verification body</strong>",
            )

        self.assertEqual(message_id, "email_123")
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(payload["from"], "TIS <info@tisplatform.com>")
        self.assertEqual(payload["to"], ["owner@example.com"])
        self.assertEqual(payload["reply_to"], ["support@tisplatform.com"])
        self.assertEqual(payload["subject"], "Verify email")
        self.assertEqual(payload["text"], "Verification body")
        self.assertEqual(payload["html"], "<strong>Verification body</strong>")
        self.assertEqual(captured["timeout"], 9)
        self.assertEqual(
            captured["request"].get_header("Authorization"),
            "Bearer re_secret_test_key",
        )

    def test_missing_api_key_is_reported_as_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(email_service.EmailServiceNotConfigured):
                email_service.send_email(
                    to="owner@example.com",
                    subject="Verify email",
                    text="Verification body",
                )

    def test_resend_error_redacts_api_key(self):
        api_key = "re_secret_should_not_leak"
        provider_error = HTTPError(
            email_service.RESEND_EMAILS_URL,
            422,
            "Unprocessable Entity",
            hdrs=None,
            fp=io.BytesIO(
                json.dumps({"message": f"Invalid credential {api_key}"}).encode("utf-8")
            ),
        )
        self.addCleanup(provider_error.close)
        with (
            patch.dict(
                os.environ,
                {
                    "RESEND_API_KEY": api_key,
                    "EMAIL_FROM": "info@tisplatform.com",
                    "EMAIL_REPLY_TO": "support@tisplatform.com",
                },
                clear=True,
            ),
            patch.object(email_service, "urlopen", side_effect=provider_error),
        ):
            with self.assertRaises(email_service.EmailDeliveryError) as raised:
                email_service.send_email(
                    to="owner@example.com",
                    subject="Verify email",
                    text="Verification body",
                )

        self.assertIn("HTTP 422", str(raised.exception))
        self.assertNotIn(api_key, str(raised.exception))
        self.assertIn("[redacted]", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
