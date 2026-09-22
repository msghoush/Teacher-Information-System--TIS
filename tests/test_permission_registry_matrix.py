"""Governed registry evidence matrix (Phase 3 whole-application permission audit).

Every registered permission key is classified here with a reviewed status and
mechanically-discovered consumers. This is NOT a second registry: the registry of
record is `permission_registry`; this module only asserts evidence about it.

Status: A active-enforced | B platform-only (enforced by guard) | C alias/composite
        (governed by another guard/identity) | D dormant/reserved (no enforcement) |
        E unresolved (must never appear).

The test fails when: a newly registered key has no classification, a key classified
A/B/C has no discovered guard consumer, a key classified D gains a guard consumer
(reclassify it), a recorded consumer disappears, or any key is E.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TIS_SESSION_SECRET", "permission-registry-matrix-secret-long-enough")

import ast
import collections

import auth
import permission_registry as registry
from tests import permission_audit_support as support

CLASSIFICATION = {
    # --- dashboard
    "dashboard.view": ("A", ('authorization.py',)),
    "dashboard.view_branch_summary": ("A", ('templates/dashboard.html',)),
    "dashboard.view_reports": ("A", ('templates/dashboard.html',)),
    "dashboard.export_reports": ("A", ('authorization.py', 'templates/dashboard.html')),
    "dashboard.view_all_schools": ("D", ()),
    # --- hiring_plan
    "hiring_plan.view": ("A", ('authorization.py', 'templates/dashboard.html')),
    "hiring_plan.edit": ("A", ('authorization.py', 'templates/dashboard.html')),
    "hiring_plan.export": ("A", ('main.py', 'templates/dashboard.html')),
    # --- reports
    "reports.view": ("D", ()),
    "reports.export": ("A", ('authorization.py',)),
    # --- users
    "users.view": ("A", ('auth.py', 'authorization.py', 'routers/users.py', 'templates/system_configuration_schools.html')),
    "users.create": ("A", ('authorization.py', 'templates/users.html')),
    "users.edit_profile": ("A", ('auth.py', 'authorization.py', 'routers/users.py')),
    "users.assign_position": ("A", ('auth.py', 'authorization.py', 'routers/users.py')),
    "users.assign_role": ("A", ('auth.py', 'authorization.py', 'routers/users.py')),
    "users.assign_branch": ("A", ('auth.py', 'authorization.py', 'routers/users.py')),
    "users.activate_deactivate": ("A", ('auth.py', 'authorization.py', 'routers/users.py', 'templates/users.html')),
    "users.reset_password": ("A", ('auth.py', 'authorization.py', 'routers/users.py')),
    "users.delete": ("A", ('auth.py', 'authorization.py', 'routers/users.py')),
    "users.bulk_delete": ("A", ('auth.py', 'authorization.py', 'routers/users.py')),
    "users.manage_profile_photo": ("A", ('authorization.py', 'templates/base.html')),
    # --- teachers
    "teachers.view": ("A", ('authorization.py', 'templates/dashboard.html')),
    "teachers.create": ("A", ('authorization.py', 'routers/teachers.py')),
    "teachers.edit": ("A", ('authorization.py', 'routers/teachers.py')),
    "teachers.delete": ("A", ('auth.py', 'authorization.py', 'routers/teachers.py')),
    "teachers.bulk_delete": ("A", ('authorization.py', 'routers/teachers.py')),
    "teachers.assign_subjects": ("A", ('routers/teachers.py',)),
    "teachers.manage_qualifications": ("A", ('routers/teachers.py',)),
    "teachers.manage_capacity": ("A", ('routers/teachers.py',)),
    "teachers.copy_year_data": ("A", ('authorization.py', 'routers/teachers.py')),
    "teachers.import": ("D", ()),
    "teachers.export": ("D", ()),
    # --- subjects
    "subjects.view": ("A", ('authorization.py', 'templates/dashboard.html')),
    "subjects.create": ("A", ('authorization.py', 'routers/subjects.py')),
    "subjects.edit": ("A", ('authorization.py', 'routers/subjects.py')),
    "subjects.delete": ("A", ('auth.py', 'authorization.py', 'routers/subjects.py')),
    "subjects.copy_year_data": ("A", ('authorization.py', 'routers/subjects.py')),
    "subjects.manage_colors": ("D", ()),
    "subjects.import": ("A", ('authorization.py', 'routers/subjects.py', 'templates/subjects.html')),
    "subjects.export": ("A", ('authorization.py', 'templates/subjects.html')),
    # --- planning
    "planning.view": ("A", ('authorization.py', 'templates/dashboard.html')),
    "planning.create_section": ("A", ('authorization.py', 'routers/planning.py')),
    "planning.edit_section": ("A", ('authorization.py', 'routers/planning.py')),
    "planning.delete_section": ("A", ('auth.py', 'authorization.py', 'routers/planning.py')),
    "planning.assign_teacher": ("A", ('routers/planning.py', 'templates/edit_planning.html')),
    "planning.manage_homeroom": ("A", ('routers/planning.py', 'templates/edit_planning.html')),
    "planning.copy_year_data": ("A", ('authorization.py', 'routers/planning.py')),
    "planning.import": ("D", ()),
    "planning.export": ("D", ()),
    "curriculum.adjust": ("A", ('authorization.py', 'routers/planning.py', 'routers/subjects.py')),
    # --- students
    "students.view": ("A", ('routers/students.py', 'routers/students_ui.py', 'ui_shell.py')),
    "students.view_all_branches": ("A", ('routers/students_ui.py',)),
    "students.create": ("A", ('routers/students.py', 'routers/students_ui.py')),
    "students.edit": ("A", ('routers/students_ui.py',)),
    "students.activate_deactivate": ("A", ('routers/students_ui.py',)),
    "students.delete": ("A", ('routers/students.py', 'routers/students_ui.py')),
    "students.bulk_delete": ("A", ('routers/students.py', 'routers/students_ui.py')),
    "students.force_delete_history": ("A", ('routers/students.py', 'routers/students_ui.py')),
    "students.manage_identifiers": ("A", ('routers/students.py',)),
    "students.manage_placements": ("A", ('routers/students.py', 'routers/students_ui.py')),
    "students.import": ("D", ()),
    "students.export": ("D", ()),
    # --- talent_programs
    "talent_programs.view": ("A", ('routers/talent_programs.py', 'ui_shell.py')),
    "talent_programs.manage": ("A", ('routers/talent_programs.py',)),
    "talent_programs.govern": ("A", ('routers/talent_programs.py',)),
    "talent_programs.delete": ("A", ('routers/talent_programs.py',)),
    "talent_programs.delete_competency": ("A", ('routers/talent_programs.py',)),
    "talent_programs.delete_rubric_level": ("A", ('routers/talent_programs.py',)),
    # --- talent_assessment_cycles
    "talent_assessment_cycles.view": ("A", ('routers/talent_analytics.py', 'routers/talent_assessment_cycles.py', 'routers/talent_evaluation_plans.py')),
    "talent_assessment_cycles.manage": ("A", ('routers/talent_assessment_cycles.py', 'routers/talent_evaluation_plans.py')),
    "talent_assessment_cycles.view_population": ("A", ('routers/talent_assessment_cycles.py',)),
    "talent_assessment_cycles.govern": ("A", ('routers/talent_assessment_cycles.py',)),
    # --- talent_evaluation_plans
    "talent_evaluation_plans.view": ("A", ('routers/talent_evaluation_plans.py', 'ui_shell.py')),
    "talent_evaluation_plans.manage": ("A", ('routers/talent_evaluation_plans.py',)),
    "talent_evaluation_plans.govern": ("A", ('routers/talent_evaluation_plans.py',)),
    "talent_evaluation_plans.delete_period": ("A", ('routers/talent_evaluation_plans.py',)),
    "talent_evaluation_plans.manage_timeline": ("A", ('routers/talent_evaluation_plans.py',)),
    "talent_evaluation_plans.select_period": ("A", ('routers/talent_evaluation_plans.py',)),
    # --- talent_assessments
    "talent_assessments.view": ("A", ('routers/talent_assessment_cycles.py', 'routers/talent_assessments.py', 'ui_shell.py')),
    "talent_assessments.manage": ("A", ('routers/talent_assessments.py',)),
    "talent_assessments.complete": ("A", ('routers/talent_assessments.py',)),
    "talent_assessments.delete": ("A", ('routers/talent_assessments.py',)),
    "talent_assessments.reset_for_reassessment": ("A", ('routers/talent_assessments.py',)),
    # --- talent_review_candidates
    "talent_review_candidates.view": ("A", ('routers/students_ui.py', 'routers/talent_analytics.py', 'routers/talent_learner_profiles.py', 'routers/talent_programs.py', 'routers/talent_review_candidates.py', 'ui_shell.py')),
    "talent_review_candidates.manage": ("A", ('routers/talent_review_candidates.py',)),
    # --- talent_official_identifications
    "talent_official_identifications.view": ("A", ('routers/students_ui.py', 'routers/talent_analytics.py', 'routers/talent_learner_profiles.py', 'routers/talent_official_identifications.py')),
    "talent_official_identifications.record": ("A", ('routers/talent_official_identifications.py',)),
    # --- talent_educator_inputs
    "talent_educator_inputs.view": ("A", ('routers/students_ui.py', 'routers/talent_educator_inputs.py', 'routers/talent_learner_profiles.py')),
    "talent_educator_inputs.add": ("A", ('routers/talent_educator_inputs.py',)),
    "talent_educator_inputs.amend": ("A", ('routers/talent_educator_inputs.py',)),
    # --- talent_learner_profiles
    "talent_learner_profiles.view": ("A", ('routers/students_ui.py', 'routers/talent_analytics.py', 'routers/talent_learner_profiles.py', 'ui_shell.py')),
    # --- talent_analytics
    "talent_analytics.view": ("A", ('routers/talent_programs.py', 'ui_shell.py')),
    "talent_analytics.view_students": ("A", ('routers/talent_analytics.py',)),
    # --- timetable
    "timetable.view": ("A", ('authorization.py',)),
    "timetable.create": ("A", ('authorization.py', 'routers/timetable.py')),
    "timetable.edit": ("A", ('authorization.py', 'routers/timetable.py')),
    "timetable.delete": ("A", ('auth.py', 'authorization.py', 'routers/timetable.py')),
    "timetable.manage_blocks": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_timetable.html')),
    "timetable.manage_settings": ("A", ('authorization.py', 'main.py', 'routers/timetable.py', 'templates/system_configuration_timetable.html', 'templates/timetable.html')),
    "timetable.manage_teacher_rules": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_timetable.html')),
    "timetable.generate": ("A", ('authorization.py', 'routers/timetable.py')),
    "timetable.publish": ("A", ('authorization.py', 'routers/timetable.py')),
    "timetable.lock_lessons": ("A", ('authorization.py', 'routers/timetable.py')),
    "timetable.archive_versions": ("A", ('authorization.py', 'routers/timetable.py')),
    "timetable.delete_versions": ("A", ('routers/timetable.py',)),
    "timetable.delete_working": ("A", ('authorization.py', 'routers/timetable.py')),
    "timetable.export": ("A", ('authorization.py', 'routers/timetable.py', 'templates/timetable.html')),
    # --- academic_calendar
    "calendar.view": ("A", ('authorization.py',)),
    "calendar.create": ("A", ('authorization.py', 'routers/academic_calendar.py', 'templates/academic_calendar.html')),
    "calendar.edit": ("A", ('authorization.py', 'routers/academic_calendar.py', 'templates/academic_calendar.html')),
    "calendar.delete": ("A", ('auth.py', 'authorization.py', 'routers/academic_calendar.py', 'templates/academic_calendar.html')),
    "calendar.assign_targets": ("A", ('routers/academic_calendar.py',)),
    "calendar.manage_event_types": ("A", ('authorization.py', 'main.py', 'routers/academic_calendar.py', 'templates/academic_calendar.html')),
    "calendar.send_notifications": ("A", ('routers/academic_calendar.py',)),
    "calendar.export": ("A", ('authorization.py', 'templates/academic_calendar.html')),
    # --- observations
    "observations.view": ("A", ('authorization.py',)),
    "observations.create_formal": ("A", ('authorization.py', 'routers/observations.py')),
    "observations.create_non_formal": ("A", ('authorization.py', 'routers/observations.py')),
    "observations.edit_draft": ("A", ('authorization.py', 'routers/observations.py')),
    "observations.submit": ("D", ()),
    "observations.delete": ("A", ('auth.py', 'authorization.py', 'routers/observations.py')),
    "observations.sign_evaluator": ("A", ('routers/observations.py', 'templates/observation_form.html')),
    "observations.sign_teacher": ("A", ('authorization.py',)),
    "observations.self_evaluate": ("A", ('authorization.py',)),
    "observations.unlock": ("A", ('routers/observations.py',)),
    "observations.view_reports": ("A", ('routers/observations.py', 'templates/observations.html')),
    "observations.export_reports": ("A", ('authorization.py', 'templates/observation_detail.html', 'templates/observation_history.html', 'templates/observations.html')),
    "observations.manage_templates": ("D", ()),
    # --- ai
    # Enforced indirectly: see INDIRECT_CONSUMERS (AST-verified) and the runtime test in
    # tests/test_ai_entitlement_service.py. The registry constant alone is NOT evidence.
    "ai.use": ("A", ('saas/ai_entitlement_service.py',)),
    # --- notifications
    "notifications.view": ("A", ('authorization.py',)),
    "notifications.send_direct": ("A", ('authorization.py', 'main.py')),
    "notifications.broadcast": ("A", ('authorization.py', 'main.py')),
    "notifications.resolve": ("A", ('authorization.py', 'main.py', 'templates/notifications.html')),
    "notifications.mark_read": ("A", ('authorization.py', 'main.py', 'templates/notifications.html')),
    "notifications.archive": ("A", ('authorization.py', 'main.py', 'templates/notifications.html')),
    # --- school_management
    "schools.view": ("A", ('authorization.py', 'main.py')),
    "schools.create": ("B", ('authorization.py', 'main.py')),
    "schools.edit": ("A", ('authorization.py', 'main.py')),
    "schools.delete": ("B", ('authorization.py', 'main.py')),
    "schools.manage_all_schools": ("B", ('main.py',)),
    "branches.view": ("A", ('authorization.py', 'main.py', 'saas/customer_journey_service.py')),
    "branches.create": ("A", ('authorization.py', 'main.py', 'saas/customer_journey_service.py', 'templates/system_configuration_branches.html', 'templates/system_configuration_schools.html')),
    "branches.edit": ("A", ('authorization.py', 'main.py', 'saas/customer_journey_service.py', 'templates/system_configuration_branches.html', 'templates/system_configuration_schools.html')),
    "branches.activate_deactivate": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_branches.html', 'templates/system_configuration_schools.html')),
    "branches.delete": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_branches.html', 'templates/system_configuration_schools.html')),
    "academic_years.view": ("A", ('auth.py', 'authorization.py', 'main.py')),
    "academic_years.create": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_schools.html', 'templates/system_configuration_years.html')),
    "academic_years.activate": ("A", ('auth.py', 'authorization.py', 'main.py', 'templates/system_configuration_schools.html', 'templates/system_configuration_years.html')),
    "academic_years.delete": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_schools.html')),
    "branding.view": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_schools.html', 'ui_shell.py')),
    "branding.manage_school_logos": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_logos.html', 'ui_shell.py')),
    "branding.manage_branch_logos": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_logos.html', 'ui_shell.py')),
    # --- configuration
    "configuration.view": ("A", ('authorization.py', 'main.py')),
    "subscriptions.manage_billing": ("A", ('main.py', 'saas/customer_journey_service.py', 'saas/subscription_change_service.py')),
    "configuration.manage_permissions": ("A", ('authorization.py', 'main.py', 'routers/users.py', 'ui_shell.py')),
    "configuration.manage_degrees": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_qualifications.html')),
    "configuration.manage_specializations": ("A", ('authorization.py', 'main.py', 'templates/system_configuration_qualifications.html')),
    "configuration.view_audit_log": ("B", ('main.py',)),
    "configuration.export_audit_log": ("B", ('authorization.py',)),
    "configuration.manage_global_defaults": ("D", ()),
    "design_control.manage": ("B", ('authorization.py', 'main.py', 'ui_shell.py')),
    # --- platform
    "demo_requests.view": ("B", ('authorization.py', 'main.py')),
    "demo_requests.export": ("B", ('authorization.py',)),
    "demo_requests.update_status": ("B", ('authorization.py', 'templates/demo_requests.html')),
    "promo_codes.view": ("B", ('main.py', 'saas/router.py')),
    "promo_codes.manage": ("B", ('main.py', 'saas/router.py')),
    # --- system_owner
    "system_owner.full_access": ("B", ('authorization.py',)),
    "system_owner.switch_all_schools": ("B", ('main.py',)),
    "system_owner.manage_subscriptions": ("D", ()),
    "system_owner.create_subscription_school": ("D", ()),
    "system_owner.manage_global_role_permissions": ("B", ('main.py',)),
    "system_owner.manage_developer_accounts": ("C", ()),
    "system_owner.manage_ownership": ("C", ()),
    "system_owner.transfer_ownership": ("C", ()),
    "system_owner.run_startup_repairs": ("D", ()),
    "system_owner.view_cross_school_audit": ("C", ('main.py',)),
    "system_owner.export_cross_school_data": ("C", ('authorization.py',)),
}

DORMANT_REASONS = {
    "reports.view": "No standalone Reports page; the dashboard Reports tab is governed by dashboard.view_reports.",
    "teachers.import": "No teacher import route or control exists.",
    "teachers.export": "No teacher export route or control exists.",
    "subjects.manage_colors": "Subject color is auto-derived; no manual color editing exists.",
    "planning.import": "No planning import route or control exists (a prior KMS note claiming a consumer was stale).",
    "planning.export": "No planning export route or control exists (a prior KMS note claiming a consumer was stale).",
    "students.import": "Governance prerequisite only (owner-approved); no roster import route or control exists yet (M6 backend implementation is separate, later work).",
    "students.export": "Governance prerequisite only (owner-approved); no roster export route or control exists yet (M6 backend implementation is separate, later work).",
    "observations.submit": "Documented alias of observations.sign_evaluator but no code path evaluates it; enforcement is sign_evaluator only.",
    "observations.manage_templates": "Observation rubric is an auto-seeded fixture; no template management route exists.",
    "dashboard.view_all_schools": "Platform-only; referenced only in a denial-message label. The all-school scope gate is the access scope identity, not this key.",
    "configuration.manage_global_defaults": "Platform-only; no global-defaults workflow exists.",
    "system_owner.manage_subscriptions": "Platform-only; subscription management is delegated to the SaaS surface.",
    "system_owner.create_subscription_school": "Platform-only; no route exists.",
    "system_owner.run_startup_repairs": "Platform-only; startup repairs are automatic, no route exists.",
}

ALIAS_REASONS = {
    "system_owner.manage_developer_accounts": "Owner-identity gate (auth.is_platform_owner) on /platform/developers routes; key cited in the denial only.",
    "system_owner.manage_ownership": "Owner-identity gate; key cited in the denial only.",
    "system_owner.transfer_ownership": "Primary-owner-identity gate; key cited in the denial only.",
    "system_owner.view_cross_school_audit": "match=any alias of configuration.view_audit_log on the single global audit log.",
    "system_owner.export_cross_school_data": "match=any alias of configuration.export_audit_log on the single global audit log.",
}

# Alias keys whose enforcement is identity based (no guard literal expected).
IDENTITY_ALIASES = {
    "system_owner.manage_developer_accounts",
    "system_owner.manage_ownership",
    "system_owner.transfer_ownership",
}


# Keys whose runtime gate receives the key through a registry constant/attribute rather
# than a literal in a guard call. key -> (constant module, constant name,
# consumer file, consumer function, evaluator called with `<var>.permission_key`).
INDIRECT_CONSUMERS = {
    "ai.use": (
        "saas/ai_feature_registry.py", "AI_PERMISSION_KEY",
        "saas/ai_entitlement_service.py", "evaluate_ai_availability", "evaluate_feature_access",
    ),
}


def _verified_indirect_consumers():
    """Follow constant -> feature definition -> `feature.permission_key` -> evaluator.

    A key is credited to the consumer file only if all three links are found by AST:
    (1) the constant holds the key, (2) feature definitions pass that constant as
    `permission_key=`, (3) the named consumer function passes `<name>.permission_key`
    as an argument of the evaluator call. Any missing link yields no evidence."""
    found = {}
    for key, (const_file, const_name, consumer_file, func_name, evaluator) in INDIRECT_CONSUMERS.items():
        const_tree = ast.parse((support.ROOT / const_file).read_text(encoding="utf-8"))
        holds_key = any(
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == const_name for t in n.targets)
            and isinstance(n.value, ast.Constant)
            and n.value.value == key
            for n in ast.walk(const_tree)
        )
        used_by_definitions = any(
            isinstance(n, ast.keyword)
            and n.arg == "permission_key"
            and isinstance(n.value, ast.Name)
            and n.value.id == const_name
            for n in ast.walk(const_tree)
        )
        tree = ast.parse((support.ROOT / consumer_file).read_text(encoding="utf-8"))
        passes_to_evaluator = False
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name == func_name:
                for call in ast.walk(fn):
                    if isinstance(call, ast.Call) and support._call_name(call) == evaluator:
                        passes_to_evaluator |= any(
                            isinstance(a, ast.Attribute) and a.attr == "permission_key"
                            for a in call.args
                        )
        if holds_key and used_by_definitions and passes_to_evaluator:
            found[key] = {consumer_file}
    return found


def _discovered():
    keys = registry.ALL_PERMISSION_KEYS
    py = support.discover_python_guard_files(keys)
    tpl = support.discover_template_can_files(keys)
    indirect = _verified_indirect_consumers()
    # A bare assignment of the key to a permission-named constant is not enforcement.
    constant_files = {const_file for const_file, *_ in INDIRECT_CONSUMERS.values()}
    return {
        key: (set(py[key]) - (constant_files if key in INDIRECT_CONSUMERS else set()))
        | set(tpl[key])
        | indirect.get(key, set())
        for key in keys
    }


def build_registry_matrix():
    """Evidence matrix rows: group, assignable roles, platform-only, default roles,
    status and discovered consumers, for every registered key."""
    discovered = _discovered()
    group_of = {
        key: group["key"] for group in registry.PERMISSION_GROUPS for key, _ in group["permissions"]
    }
    rows = []
    for key in registry.ALL_PERMISSION_KEYS:
        assignable = [
            role
            for role in registry.MANAGED_ROLES
            if key in registry.constrain_role_permissions(role, {key})
        ]
        defaults = [
            role for role in registry.MANAGED_ROLES if key in registry.get_default_permissions_for_role(role)
        ]
        status, _consumers = CLASSIFICATION.get(key, ("E", ()))
        rows.append(
            {
                "key": key,
                "group": group_of[key],
                "assignable_roles": assignable,
                "platform_only": key in registry.PLATFORM_ONLY_PERMISSION_KEYS,
                "default_roles": defaults,
                "status": status,
                "consumers": sorted(discovered[key]),
            }
        )
    return rows


def test_registry_shape_is_the_audited_shape():
    assert len(registry.ALL_PERMISSION_KEYS) == 177
    assert len(registry.PERMISSION_GROUPS) == 26
    assert len(registry.ALL_PERMISSION_KEYS) == len(set(registry.ALL_PERMISSION_KEYS))


def test_every_registered_key_is_classified_and_nothing_else():
    registered = set(registry.ALL_PERMISSION_KEYS)
    classified = set(CLASSIFICATION)
    assert registered - classified == set(), "New registered key(s) need a reviewed classification"
    assert classified - registered == set(), "Classification names key(s) no longer registered"


def test_no_key_is_unresolved_and_statuses_are_valid():
    statuses = {key: value[0] for key, value in CLASSIFICATION.items()}
    assert set(statuses.values()) <= {"A", "B", "C", "D"}
    assert [k for k, s in statuses.items() if s == "E"] == []


def test_classification_counts_are_pinned():
    counts = collections.Counter(status for status, _ in CLASSIFICATION.values())
    assert dict(counts) == {"A": 143, "B": 14, "C": 5, "D": 15}


def test_active_platform_and_alias_keys_have_a_discovered_consumer():
    discovered = _discovered()
    missing = [
        key
        for key, (status, _files) in CLASSIFICATION.items()
        if status in {"A", "B"} and not discovered[key]
    ]
    assert missing == []
    alias_missing = [
        key
        for key, (status, _files) in CLASSIFICATION.items()
        if status == "C" and key not in IDENTITY_ALIASES and not discovered[key]
    ]
    assert alias_missing == []


def test_identity_aliases_are_owner_identity_gated_not_assignable():
    for key in IDENTITY_ALIASES:
        assert key in registry.OWNER_ONLY_PERMISSION_KEYS
        assert key in registry.PLATFORM_ONLY_PERMISSION_KEYS
    assert set(ALIAS_REASONS) == {k for k, (s, _) in CLASSIFICATION.items() if s == "C"}


def test_dormant_keys_have_no_guard_consumer_and_a_reason():
    discovered = _discovered()
    dormant = {key for key, (status, _files) in CLASSIFICATION.items() if status == "D"}
    assert set(DORMANT_REASONS) == dormant
    gained = {key: sorted(discovered[key]) for key in dormant if discovered[key]}
    assert gained == {}, f"Dormant key(s) now have guard consumers; reclassify: {gained}"


def test_recorded_consumers_are_still_discovered():
    discovered = _discovered()
    lost = {
        key: sorted(set(files) - discovered[key])
        for key, (_status, files) in CLASSIFICATION.items()
        if set(files) - discovered[key]
    }
    assert lost == {}


def test_platform_only_classification_is_consistent_with_registry():
    for key, (status, _files) in CLASSIFICATION.items():
        platform = key in registry.PLATFORM_ONLY_PERMISSION_KEYS
        if status in {"B", "C"}:
            assert platform, key
        if status == "A":
            assert not platform, key
    assert len(registry.PLATFORM_ONLY_PERMISSION_KEYS) == 24
    assert len(registry.DEVELOPER_ONLY_PERMISSION_KEYS) == 22
    assert len(registry.OWNER_ONLY_PERMISSION_KEYS) == 4
    assert len(registry.ADMINISTRATOR_ONLY_PERMISSION_KEYS) == 1
    assert len(registry.LIMITED_READ_ONLY_PERMISSION_KEYS) == 11


def test_platform_only_keys_are_never_assignable_or_default_to_any_tenant_role():
    for row in build_registry_matrix():
        if row["platform_only"]:
            assert row["assignable_roles"] == [], row["key"]
            assert row["default_roles"] == [], row["key"]


def test_role_assignability_matrix_matches_documented_constraints():
    for row in build_registry_matrix():
        if row["platform_only"]:
            continue
        key = row["key"]
        if key in registry.ADMINISTRATOR_ONLY_PERMISSION_KEYS:
            assert row["assignable_roles"] == [auth.ROLE_ADMINISTRATOR]
        elif key in registry.LIMITED_READ_ONLY_PERMISSION_KEYS:
            assert row["assignable_roles"] == list(registry.MANAGED_ROLES)
        else:
            assert row["assignable_roles"] == [
                auth.ROLE_ADMINISTRATOR,
                auth.ROLE_EDITOR,
                auth.ROLE_USER,
            ]
        # A default grant must always be assignable.
        assert set(row["default_roles"]) <= set(row["assignable_roles"]), key


def test_dormant_keys_are_not_offered_by_any_active_ui_guard_or_nav():
    """No template `can(...)`/nav item is keyed on a dormant permission."""
    dormant = [key for key, (status, _f) in CLASSIFICATION.items() if status == "D"]
    tpl = support.discover_template_can_files(dormant)
    assert {key: files for key, files in tpl.items() if files} == {}
    js = support.discover_static_js_files(dormant)
    assert {key: files for key, files in js.items() if files} == {}


def test_ai_use_is_enforced_through_the_ai_entitlement_service():
    """`ai.use` evidence is the verified constant -> feature.permission_key -> evaluator chain."""
    assert _verified_indirect_consumers() == {"ai.use": {"saas/ai_entitlement_service.py"}}
    # The registry constant alone (a bare assignment) is never credited as a consumer.
    assert "saas/ai_feature_registry.py" not in _discovered()["ai.use"]
    assert _discovered()["ai.use"] == {"saas/ai_entitlement_service.py"}
