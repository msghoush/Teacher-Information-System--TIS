from datetime import datetime, timezone

from saas import commercial_access_service, commercial_badge_service, promo_grant_service


def test_commercial_badges_are_source_plan_and_state_aware():
    promo_active = commercial_badge_service.build_badge_from_access(
        commercial_access_service.CommercialAccessState(
            False,
            kind="promo",
            commercial_state="active",
            current_plan_code="enterprise_ai",
            current_plan_name="Enterprise AI",
        ),
        promo_resolution=promo_grant_service.PromoGrantResolution(
            "resolved", "resolved", 1, status="active"
        ),
    )
    promo_recovery = commercial_badge_service.build_badge_from_access(
        commercial_access_service.CommercialAccessState(
            True,
            kind="promo",
            commercial_state="expired",
            current_plan_code="enterprise_ai",
            current_plan_name="Enterprise AI",
        ),
        promo_resolution=promo_grant_service.PromoGrantResolution(
            "resolved", "promo_grant_recovery_period", 1, status="recovery"
        ),
    )
    demo = commercial_badge_service.build_badge_from_access(
        commercial_access_service.CommercialAccessState(
            False, kind="demo", commercial_state="active"
        )
    )
    paid = commercial_badge_service.build_badge_from_access(
        commercial_access_service.CommercialAccessState(
            False,
            kind="subscription",
            commercial_state="active",
            current_plan_code="professional",
            current_plan_name="Professional",
        )
    )

    assert (promo_active.icon, promo_active.access_label, promo_active.plan_tone) == (
        "sparkles", "Promotional Access", "enterprise"
    )
    assert promo_recovery.status_label == "Recovery Period"
    assert promo_recovery.status_tone == "warning"
    assert (demo.icon, demo.access_label, demo.status_label) == (
        "eye", "Demo Access", "Active"
    )
    assert (paid.icon, paid.access_label, paid.plan_name) == (
        "shield", "Subscription Active", "Professional"
    )


def test_badge_template_has_compact_accessible_authority_markers():
    template = open("templates/_commercial_badge.html", encoding="utf-8").read()
    css = open("static/css/commercial-badges.css", encoding="utf-8").read()
    app_shell_css = open("static/css/app-shell.css", encoding="utf-8").read()
    operational = open("templates/base.html", encoding="utf-8").read()
    operational_shell = open("ui_shell.py", encoding="utf-8").read()
    account = open("templates/saas/account.html", encoding="utf-8").read()
    promo = open("templates/saas/promo_commercial_access.html", encoding="utf-8").read()

    assert 'aria-label="{{ badge.aria_label }}"' in template
    assert 'data-commercial-source="{{ badge.source }}"' in template
    assert "commercial-badge--compact" not in template
    assert ".commercial-badge--promo" in css
    assert ".commercial-badge--demo" in css
    assert ".commercial-badge--paid" in css
    assert "@media (max-width: 640px)" in css
    assert "_commercial_badge.html" not in operational
    assert "shell.commercial_badge" not in operational
    assert "header-commercial-identity" not in operational
    assert "commercial_badge_service" not in operational_shell
    assert ".header-commercial-identity" not in app_shell_css
    assert 'commercial_badge(organization_account.commercial_badge, "full")' in account
    assert 'commercial_badge(commercial_badge_view, "full")' in promo


def test_unresolved_promo_placeholder_does_not_claim_promo_authority():
    badge = commercial_badge_service.build_badge_from_access(
        commercial_access_service.CommercialAccessState(
            True,
            kind="promo",
            reason_code="activation_required",
            commercial_state="activation_required",
        ),
        promo_resolution=promo_grant_service.PromoGrantResolution(
            "manual_review", "missing_promo_grant", 1
        ),
    )

    assert badge is None


def test_expired_promo_access_copy_is_source_aware():
    presentation = commercial_access_service.customer_access_presentation(
        commercial_access_service.CommercialAccessState(
            True,
            kind="promo",
            commercial_state=commercial_access_service.EXPIRED,
            current_period_end=datetime(2027, 8, 25, tzinfo=timezone.utc),
            recovery_period=True,
        )
    )

    assert presentation.title == "Promotional Access Expired"
    assert "25 Aug 2027" in presentation.message
    assert "organization data remains preserved" in presentation.message
    assert presentation.action_label == "Continue with a Subscription"
    assert "Renew Subscription" not in presentation.message
