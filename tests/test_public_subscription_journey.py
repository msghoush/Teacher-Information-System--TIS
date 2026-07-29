import re
from pathlib import Path
import unittest
from unittest.mock import patch

import saas.models
from saas import service
from tests import test_saas_phase1 as phase1_tests


ROOT = Path(__file__).resolve().parents[1]
LANDING_PAGE = ROOT / "tis-landing-website" / "src" / "app" / "page.tsx"
LANDING_CSS = ROOT / "tis-landing-website" / "src" / "app" / "globals.css"


class PublicSubscriptionJourneyTests(unittest.TestCase):
    def setUp(self):
        self.harness = phase1_tests.SaaSPhase1Tests(methodName="runTest")
        self.harness.setUp()
        self.client = self.harness.client

    def tearDown(self):
        self.harness.tearDown()

    def test_public_signup_accepts_missing_valid_and_unknown_preferred_plan(self):
        missing = self.client.get("/saas/signup?intent=subscribe")
        self.assertEqual(missing.status_code, 200)
        self.assertIn('name="intent" value="subscribe"', missing.text)
        self.assertIn('name="preferred_plan" value=""', missing.text)

        valid = self.client.get(
            "/saas/signup?intent=subscribe&preferred_plan=professional"
        )
        self.assertEqual(valid.status_code, 200)
        self.assertIn(
            'name="preferred_plan" value="professional"',
            valid.text,
        )
        self.assertEqual(
            self.client.cookies.get(service.SAAS_PREFERRED_PLAN_COOKIE),
            "professional",
        )

        unknown = self.client.get(
            "/saas/signup",
            params={
                "intent": "subscribe",
                "preferred_plan": "../../checkout",
            },
        )
        self.assertEqual(unknown.status_code, 200)
        self.assertIn('name="preferred_plan" value=""', unknown.text)
        self.assertIsNone(
            self.client.cookies.get(service.SAAS_PREFERRED_PLAN_COOKIE)
        )

    def test_valid_preferred_plan_survives_public_account_registration(self):
        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return "email_public_subscription"

        with patch("email_service.send_email", side_effect=fake_send_email):
            response = self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Public",
                    "last_name": "Subscriber",
                    "email": "public-subscriber@academy.edu",
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                    "intent": "subscribe",
                    "preferred_plan": "starter",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/auth/verification-sent", response.headers["location"])
        self.assertEqual(
            self.client.cookies.get(service.SAAS_PREFERRED_PLAN_COOKIE),
            "starter",
        )
        self.assertEqual(len(sent_messages), 1)

        db = self.harness._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized="public-subscriber@academy.edu"
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

    def test_incomplete_onboarding_cannot_open_plan_selection(self):
        self.harness._signup_and_verify("incomplete-subscription@academy.edu")
        organization_uuid = self.harness._start_pending_organization()

        response = self.client.get(
            f"/saas/onboarding/{organization_uuid}/plan",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["location"].startswith("/saas/account?notice="))

    def test_eligible_preference_is_presented_without_selecting_or_checkout(self):
        organization_uuid = (
            self.harness._complete_pending_organization_to_ready_for_checkout(
                "preferred-eligible@academy.edu"
            )
        )
        preference_response = self.client.get(
            "/saas/signup?intent=subscribe&preferred_plan=professional",
            follow_redirects=False,
        )
        self.assertEqual(preference_response.status_code, 302)

        db = self.harness._db()
        try:
            professional = db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code="professional"
            ).one()
            professional_id = professional.id
        finally:
            db.close()

        response = self.client.get(
            f"/saas/onboarding/{organization_uuid}/plan"
        )

        self.assertEqual(response.status_code, 200)
        professional_option = re.search(
            rf'<option value="{professional_id}" ([^>]*)>',
            response.text,
        )
        self.assertIsNotNone(professional_option)
        self.assertIn("selected", professional_option.group(1))
        self.assertNotIn("disabled", professional_option.group(1))
        self.assertEqual(
            self.client.cookies.get(service.SAAS_PREFERRED_PLAN_COOKIE),
            "professional",
        )

        db = self.harness._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            self.assertIsNone(organization.selected_plan_id)
            self.assertEqual(db.query(saas.models.CheckoutSession).count(), 0)
            self.assertEqual(db.query(saas.models.PaymentAttempt).count(), 0)
        finally:
            db.close()

    def test_ineligible_lower_preference_is_cleared_after_capacity_validation(self):
        organization_uuid = (
            self.harness._complete_pending_organization_to_ready_for_checkout(
                "preferred-capacity@academy.edu"
            )
        )
        preference_response = self.client.get(
            "/saas/signup?intent=subscribe&preferred_plan=starter",
            follow_redirects=False,
        )
        self.assertEqual(preference_response.status_code, 302)

        db = self.harness._db()
        try:
            starter = db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code="starter"
            ).one()
            starter_id = starter.id
        finally:
            db.close()

        response = self.client.get(
            f"/saas/onboarding/{organization_uuid}/plan"
        )

        self.assertEqual(response.status_code, 200)
        normalized_response_text = " ".join(response.text.split())
        self.assertIn(
            "Your initial plan preference was updated because your organization "
            "setup requires a different capacity level.",
            normalized_response_text,
        )
        starter_option = re.search(
            rf'<option value="{starter_id}" ([^>]*)>',
            response.text,
        )
        self.assertIsNotNone(starter_option)
        self.assertIn("disabled", starter_option.group(1))
        self.assertNotIn("selected", starter_option.group(1))
        self.assertIsNone(
            self.client.cookies.get(service.SAAS_PREFERRED_PLAN_COOKIE)
        )

        db = self.harness._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            self.assertIsNone(organization.selected_plan_id)
            self.assertEqual(
                db.query(saas.models.CheckoutSession).count(),
                0,
            )
        finally:
            db.close()

    def test_landing_pricing_ctas_use_only_safe_public_destinations(self):
        source = LANDING_PAGE.read_text(encoding="utf-8")
        css = LANDING_CSS.read_text(encoding="utf-8")
        plans_source = source.split("const plans = [", 1)[1].split(
            "const productImages",
            1,
        )[0]

        self.assertIn('href="#pricing"', source)
        self.assertIn('<section id="pricing"', source)
        self.assertIn("scroll-behavior: smooth", css)
        self.assertIn(
            '"/saas/signup?intent=subscribe&preferred_plan=starter"',
            source,
        )
        self.assertIn(
            '"/saas/signup?intent=subscribe&preferred_plan=professional"',
            source,
        )
        self.assertIn(
            '"/saas/signup?intent=subscribe&preferred_plan=enterprise_ai"',
            source,
        )
        self.assertNotIn("description:", plans_source)
        self.assertNotIn("/checkout", plans_source.lower())
        self.assertNotIn("paddle", plans_source.lower())
        self.assertNotIn("/subscription", plans_source.lower())

        custom_plan = plans_source.split('name: "Custom"', 1)[1]
        self.assertIn('ctaLabel: "Contact the TIS Team"', custom_plan)
        self.assertIn("ctaHref: contactTisTeamUrl", custom_plan)
        self.assertNotIn("signup", custom_plan)
        self.assertNotIn("checkout", custom_plan.lower())


if __name__ == "__main__":
    unittest.main()
