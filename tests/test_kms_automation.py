from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_kms_impact  # noqa: E402


def _declaration(**overrides):
    values = {
        "knowledge_impact": "yes",
        "summary": "Update subscription lifecycle behavior.",
        "affected_areas": ("subscriptions",),
        "kms_files_updated": ("docs/CHANGE_HISTORY.md",),
        "no_impact_reason": "",
        "major_change_override": "no",
    }
    values.update(overrides)
    return check_kms_impact.ImpactDeclaration(**values)


def test_parse_declaration_supports_the_repository_schema():
    declaration = check_kms_impact.parse_declaration_text(
        """
knowledge_impact: yes
summary: Update subscription lifecycle behavior.
affected_areas:
  - subscriptions
kms_files_updated:
  - docs/CHANGE_HISTORY.md
no_impact_reason:
major_change_override: no
"""
    )

    assert declaration.knowledge_impact == "yes"
    assert declaration.affected_areas == ("subscriptions",)
    assert declaration.kms_files_updated == ("docs/CHANGE_HISTORY.md",)


def test_major_change_classification_covers_core_behavior_paths():
    assert check_kms_impact.is_major_change("main.py")
    assert check_kms_impact.is_major_change("saas/subscription_lifecycle_service.py")
    assert check_kms_impact.is_major_change("routers/academic_calendar.py")
    assert check_kms_impact.is_major_change(".github/workflows/deploy-on-master.yml")
    assert check_kms_impact.is_major_change("tis-landing-website/src/app/page.tsx")
    assert not check_kms_impact.is_major_change("docs/README.md")
    assert not check_kms_impact.is_major_change("tis-landing-website/src/app/globals.css")


def test_impact_yes_requires_changed_declared_markdown():
    errors = check_kms_impact.validate_declaration(
        _declaration(),
        [".kms-impact.yml", "main.py"],
    )

    assert any("Declared KMS file did not change" in error for error in errors)


def test_major_change_no_impact_requires_explicit_override_and_reason():
    declaration = _declaration(
        knowledge_impact="no",
        kms_files_updated=(),
        no_impact_reason="Internal rename only; behavior and public contracts are unchanged.",
    )
    changed = [".kms-impact.yml", "saas/service.py"]

    errors = check_kms_impact.validate_declaration(declaration, changed)
    assert any("major_change_override" in error for error in errors)

    overridden = _declaration(
        knowledge_impact="no",
        kms_files_updated=(),
        no_impact_reason="Internal rename only; behavior and public contracts are unchanged.",
        major_change_override="yes",
    )
    assert check_kms_impact.validate_declaration(overridden, changed) == []


def test_changed_kms_markdown_must_be_declared():
    errors = check_kms_impact.validate_declaration(
        _declaration(),
        [".kms-impact.yml", "docs/CHANGE_HISTORY.md", "docs/PROJECT_STATE.md"],
    )

    assert any("docs/PROJECT_STATE.md" in error for error in errors)
