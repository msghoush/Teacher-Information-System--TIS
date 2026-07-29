import re
import unittest
from unittest.mock import patch

import saas.models
from saas import service
from tests import test_saas_phase1 as phase1_tests


class PostVerificationLoginJourneyTests(unittest.TestCase):
    def setUp(self):
        self.harness = phase1_tests.SaaSPhase1Tests(methodName="runTest")
        self.harness.setUp()
        self.client = self.harness.client

    def tearDown(self):
        self.harness.tearDown()

    def _register(self, email, *, intent="", preferred_plan=""):
        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return "email_post_verification_login"

        with patch("email_service.send_email", side_effect=fake_send_email):
            response = self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Journey",
                    "last_name": "Tester",
                    "email": email,
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                    "intent": intent,
                    "preferred_plan": preferred_plan,
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(sent_messages), 1)
        token_match = re.search(
            r"token=([A-Za-z0-9._\-]+)",
            sent_messages[0]["text"],
        )
        self.assertIsNotNone(token_match)
        return token_match.group(1)

    def _remove_account_for_reregistration(self, email):
        db = self.harness._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized=email
            ).one()
            account_id = account.id
            for model in (
                saas.models.SaaSAuthIdentity,
                saas.models.SaaSSession,
                saas.models.SaaSEmailVerificationToken,
                saas.models.SaaSPasswordResetToken,
                saas.models.SaaSAuthEvent,
            ):
                db.query(model).filter(
                    model.saas_account_id == account_id
                ).delete(synchronize_session=False)
            db.delete(account)
            db.commit()
        finally:
            db.close()

    def test_verification_redirect_and_sign_in_form_use_get_then_post(self):
        token = self._register("verified-login@academy.edu")

        verification = self.client.get(
            f"/saas/auth/verify-email?token={token}",
            follow_redirects=False,
        )

        self.assertEqual(verification.status_code, 302)
        self.assertTrue(verification.headers["location"].startswith("/saas/login?"))
        self.assertNotIn("/saas/auth/login", verification.headers["location"])

        login_page = self.client.get(verification.headers["location"])
        self.assertEqual(login_page.status_code, 200)
        self.assertIn('<form method="post" action="/saas/auth/login">', login_page.text)
        self.assertNotIn('"detail":"Method Not Allowed"', login_page.text)

        recovery = self.client.get(
            "/saas/auth/verify-email?token=not-a-real-token"
        )
        self.assertEqual(recovery.status_code, 400)
        self.assertIn('<a class="btn" href="/saas/login">Sign in</a>', recovery.text)

    def test_fresh_verified_account_login_opens_account_setup_not_post_route(self):
        email = "fresh-login@academy.edu"
        token = self._register(email)
        self.client.get(
            f"/saas/auth/verify-email?token={token}",
            follow_redirects=False,
        )

        login = self.client.post(
            "/saas/auth/login",
            data={
                "email": email,
                "password": "strong-password-123",
                "next_path": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(login.status_code, 302)
        self.assertEqual(login.headers["location"], "/saas/account")
        account_page = self.client.get(login.headers["location"])
        self.assertEqual(account_page.status_code, 200)
        self.assertNotIn('"detail":"Method Not Allowed"', account_page.text)

    def test_get_post_handler_and_malformed_continuations_fail_safe(self):
        direct_get = self.client.get(
            "/saas/auth/login",
            follow_redirects=False,
        )
        self.assertEqual(direct_get.status_code, 302)
        self.assertEqual(direct_get.headers["location"], "/saas/login")
        self.assertEqual(self.client.get(direct_get.headers["location"]).status_code, 200)

        for continuation in (
            "/saas/auth/login",
            "/saas/onboarding/start",
            "https://example.com/saas/account",
            "/saas/account/../auth/login",
            "//example.com/saas/account",
        ):
            page = self.client.get(
                "/saas/login",
                params={"next_path": continuation},
            )
            self.assertEqual(page.status_code, 200)
            self.assertIn(
                'name="next_path" value="/saas/account"',
                page.text,
            )

    def test_reregistered_subscriber_signs_in_without_commercial_side_effects(self):
        email = "reregistered-subscriber@academy.edu"
        first_token = self._register(email)
        self.client.get(
            f"/saas/auth/verify-email?token={first_token}",
            follow_redirects=False,
        )
        self._remove_account_for_reregistration(email)

        second_token = self._register(
            email,
            intent="subscribe",
            preferred_plan="starter",
        )
        verification = self.client.get(
            f"/saas/auth/verify-email?token={second_token}",
            follow_redirects=False,
        )
        self.assertEqual(verification.status_code, 302)

        login = self.client.post(
            "/saas/auth/login",
            data={
                "email": email,
                "password": "strong-password-123",
                "next_path": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(login.status_code, 302)
        self.assertEqual(login.headers["location"], "/saas/account")
        self.assertEqual(
            self.client.cookies.get(service.SAAS_PREFERRED_PLAN_COOKIE),
            "starter",
        )

        db = self.harness._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized=email
            ).one()
            self.assertEqual(account.signup_intent, "subscribe")
            self.assertEqual(
                db.query(saas.models.PendingOrganization).count(),
                0,
            )
            self.assertEqual(db.query(saas.models.CheckoutSession).count(), 0)
            self.assertEqual(db.query(saas.models.PaymentAttempt).count(), 0)
        finally:
            db.close()

    def test_valid_subscription_continuation_and_auth_error_remain_friendly(self):
        email = "subscription-login@academy.edu"
        token = self._register(email)
        self.client.get(
            f"/saas/auth/verify-email?token={token}",
            follow_redirects=False,
        )

        valid_page = self.client.get(
            "/saas/login?next_path=/saas/subscription"
        )
        self.assertEqual(valid_page.status_code, 200)
        self.assertIn(
            'name="next_path" value="/saas/subscription"',
            valid_page.text,
        )

        invalid_password = self.client.post(
            "/saas/auth/login",
            data={
                "email": email,
                "password": "wrong-password",
                "next_path": "/saas/auth/login",
            },
            follow_redirects=False,
        )
        self.assertEqual(invalid_password.status_code, 302)
        self.assertTrue(
            invalid_password.headers["location"].startswith(
                "/saas/login?error="
            )
        )
        error_page = self.client.get(invalid_password.headers["location"])
        self.assertEqual(error_page.status_code, 200)
        self.assertIn("Invalid email or password.", error_page.text)
        self.assertNotIn('"detail":"Method Not Allowed"', error_page.text)


if __name__ == "__main__":
    unittest.main()
