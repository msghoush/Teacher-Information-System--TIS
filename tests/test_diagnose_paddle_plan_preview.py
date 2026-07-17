import importlib.util
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_paddle_plan_preview.py"
SPEC = importlib.util.spec_from_file_location("diagnose_paddle_plan_preview", SCRIPT)
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


class PaddlePlanPreviewDiagnosticTests(TestCase):
    def test_preview_sanitizer_keeps_billing_fields_and_removes_sensitive_fields(self):
        payload = {
            "id": "sub_01secret",
            "customer_id": "ctm_01secret",
            "custom_data": {"private": "value"},
            "management_urls": {"cancel": "https://secret.example"},
            "status": "active",
            "currency_code": "USD",
            "items": [{
                "quantity": 4,
                "price": {
                    "id": "pri_enterprise",
                    "product_id": "pro_enterprise",
                    "unit_price": {"amount": "14900", "currency_code": "USD"},
                    "billing_cycle": {"interval": "month", "frequency": 1},
                },
            }],
            "update_summary": {
                "credit": {"amount": "-27000", "currency_code": "USD"},
                "charge": {"amount": "55000", "currency_code": "USD"},
                "result": {"action": "charge", "amount": "28000", "currency_code": "USD"},
            },
            "immediate_transaction": {
                "card": {"last4": "4242"},
                "billing_period": {"starts_at": "2026-07-18T00:00:00Z", "ends_at": "2026-08-15T00:00:00Z"},
                "details": {
                    "totals": {"subtotal": "28000", "tax": "0", "balance": "28000", "currency_code": "USD"},
                    "line_items": [{
                        "price_id": "pri_enterprise",
                        "quantity": 4,
                        "totals": {"total": "55000"},
                        "proration": {"rate": "0.92", "billing_period": {"starts_at": "2026-07-15T00:00:00Z", "ends_at": "2026-08-15T00:00:00Z"}},
                    }],
                },
            },
        }

        result = diagnostic.sanitize_preview(payload)
        rendered = str(result)

        self.assertEqual(result["update_summary"]["credit"]["amount"], "-27000")
        self.assertEqual(result["immediate_transaction"]["details"]["totals"]["balance"], "28000")
        self.assertEqual(result["immediate_transaction"]["details"]["line_items"][0]["proration"]["rate"], "0.92")
        for forbidden in ("customer_id", "custom_data", "management_urls", "card", "4242", "ctm_01secret", "sub_01secret"):
            self.assertNotIn(forbidden, rendered)

    def test_subscription_sanitizer_reports_items_and_masks_subscription_id(self):
        result = diagnostic.sanitize_subscription({
            "id": "sub_01abcdefghijklmnopqrstuvwx",
            "status": "active",
            "items": [{"quantity": 4, "price": {"id": "pri_professional"}}],
        })
        self.assertEqual(result["subscription_id_masked"], "sub_01a...uvwx")
        self.assertEqual(result["items"][0]["quantity"], 4)
        self.assertEqual(result["items"][0]["price"]["id"], "pri_professional")

    def test_diagnostic_is_hard_gated_to_paddle_sandbox(self):
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production", "PADDLE_API_BASE_URL": "https://api.paddle.com"}, clear=False):
            with self.assertRaises(diagnostic.DiagnosticError) as blocked:
                diagnostic.require_sandbox()
        self.assertEqual(blocked.exception.code, "sandbox_required")

    def test_sandbox_configuration_is_accepted(self):
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": "https://sandbox-api.paddle.com"}, clear=False):
            diagnostic.require_sandbox()
