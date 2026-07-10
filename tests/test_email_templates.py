import unittest

import email_templates


class TransactionalEmailTemplateTests(unittest.TestCase):
    def test_verification_email_is_branded_and_has_plain_text_fallback(self):
        verification_url = "https://app.tisplatform.com/platform/account/verify-email?token=abc123"
        logo_url = "https://app.tisplatform.com/static/branding/tis/logos/TIS%20Wordmark.png"
        email = email_templates.build_email_verification_email(
            verification_url=verification_url,
            logo_url=logo_url,
        )

        self.assertEqual(email.subject, "Verify your email address | TIS Platform")
        self.assertIn("Verify your email address", email.html)
        self.assertIn(">Verify Email</a>", email.html)
        self.assertIn(verification_url, email.html)
        self.assertIn(logo_url, email.html)
        self.assertIn('alt="TIS Platform"', email.html)
        self.assertIn("<strong>Expiry:</strong>", email.html)
        self.assertIn("<strong>Security:</strong>", email.html)
        self.assertIn("TIS Platform", email.html)
        self.assertIn("Verify Email", email.text)
        self.assertIn(verification_url, email.text)
        self.assertIn("Expiry:", email.text)
        self.assertIn("Security:", email.text)

    def test_template_escapes_dynamic_content(self):
        email = email_templates.render_transactional_email(
            subject="Safe subject",
            title="Hello <script>",
            message="Welcome <b>Owner</b>",
            logo_url="https://example.com/logo.png",
            details=("User: <admin>",),
        )
        self.assertNotIn("<script>", email.html)
        self.assertNotIn("<b>Owner</b>", email.html)
        self.assertIn("&lt;script&gt;", email.html)
        self.assertIn("&lt;b&gt;Owner&lt;/b&gt;", email.html)
        self.assertIn("User: &lt;admin&gt;", email.html)

    def test_password_reset_request_uses_shared_brand_shell(self):
        email = email_templates.build_password_reset_request_email(
            requester_display="Example User (User ID 1001)",
            user_id="1001",
            platform_url="https://app.tisplatform.com/notifications",
            logo_url="https://app.tisplatform.com/static/tis-wordmark.png",
        )
        self.assertEqual(email.subject, "Password reset request | TIS Platform")
        self.assertIn("Password reset request", email.html)
        self.assertIn("Example User", email.html)
        self.assertIn("Open TIS Platform", email.html)
        self.assertIn("https://app.tisplatform.com/notifications", email.text)

    def test_saas_password_reset_email_uses_secure_customer_language(self):
        reset_url = "https://app.tisplatform.com/saas/auth/reset-password?token=reset123"
        logo_url = "https://app.tisplatform.com/static/branding/tis/logos/TIS%20Wordmark.png"
        email = email_templates.build_saas_password_reset_email(
            reset_url=reset_url,
            logo_url=logo_url,
        )

        self.assertEqual(email.subject, "Reset your TIS Account password | TIS Platform")
        self.assertIn("Reset your TIS Account password", email.html)
        self.assertIn(">Reset Password</a>", email.html)
        self.assertIn(reset_url, email.text)
        self.assertIn("expires in one hour", email.text)
        self.assertIn("If you did not request a password reset", email.text)

    def test_activation_email_uses_customer_facing_workspace_language(self):
        email = email_templates.build_tenant_activation_email(
            organization_name="Andalus Academy",
            login_url="https://app.tisplatform.com/login",
            logo_url="https://app.tisplatform.com/static/branding/tis/logos/TIS%20Wordmark%20Only%20%E2%80%93%20Dark%20Blue.png",
        )

        self.assertIn("Your School Workspace is active", email.html)
        self.assertIn("Workspace Activation is complete", email.text)
        self.assertIn("TIS Account", email.text)
        self.assertIn("TIS%20Wordmark%20Only%20%E2%80%93%20Dark%20Blue.png", email.html)
        self.assertNotIn("SaaS account", email.text)
        self.assertNotIn("Provisioning is complete", email.text)


if __name__ == "__main__":
    unittest.main()
