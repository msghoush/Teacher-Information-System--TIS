"""Dangerous-pattern scan of non-test source with a CLASSIFIED allowlist.

Each pattern is scanned repo-wide (routers, main, auth, authorization, ui_shell,
saas, services, templates). Every hit must belong to a reviewed (pattern, file)
entry whose class is one of:

  IDENTITY   valid identity/platform boundary (not a permission shortcut)
  HELPER     approved helper / canonical resolver / seed / migration / purge code
  LEGACY     legacy safe behaviour (restrictive or display-only, recorded for review)
  (ESCALATE is intentionally not an accepted class: every hit is resolved to one of the above.)

`DEFECT` / `REMEDIATE` are deliberately NOT accepted classes: a hit that is a
bypass must be fixed, not allowlisted. A NEW hit (or a changed count) in any
(pattern, file) fails the test and forces classification.
"""
import collections
import re

import pytest

from tests import permission_audit_support as support

ACCEPTED = {"IDENTITY", "HELPER", "LEGACY"}

PATTERNS = {
    # Role name/constant tokens used in code (authorisation shortcut candidates).
    "role_constant": re.compile(
        r"\bROLE_(ADMINISTRATOR|EDITOR|USER|LIMITED)\b|\bPLATFORM_ROLE_(OWNER|DEVELOPER)\b"
    ),
    "role_literal": re.compile(r"""['"](Administrator|Editor|Limited Access|Limited|Platform Owner|Developer)['"]"""),
    "is_admin_flag": re.compile(r"\b(is_admin|is_editor|is_administrator)\b"),
    "platform_identity": re.compile(
        r"\b(is_platform_user|is_platform_owner|is_platform_developer|is_primary_platform_owner)\("
    ),
    "raw_role_permission": re.compile(r"\bRolePermission\b"),
    "raw_user_override": re.compile(r"\bUserPermissionOverride\b"),
    "form_school_group_id": re.compile(r"school_group_id\s*:\s*int[^=]*=\s*(Form|Query)"),
    "orm_permission_stash": re.compile(r"\.permission_keys\s*="),
    "lru_cache": re.compile(r"\blru_cache\b|functools\.cache\b|@cache\b"),
    "module_permission_cache": re.compile(r"\b_permission_cache\b|PERMISSION_CACHE"),
}

# (pattern, file) -> (class, exact hit count, reason)
CLASSIFIED = {
    # --- role constants -------------------------------------------------
    ("role_constant", "auth.py"): ("HELPER", 20, "Canonical role normalisation / resolver / platform identity definitions."),
    ("role_constant", "main.py"): ("IDENTITY", 14, "Platform Owner/Developer identity queries and managed-role default for the Role Permissions selector; no permission shortcut."),
    ("role_constant", "routers/users.py"): ("HELPER", 12, "Assignable-role lists (governed by users.assign_role + assignment authority) and Limited default for new accounts."),
    ("role_constant", "routers/observations.py"): ("LEGACY", 1, "_is_teacher_user: restrictive compatibility rule (disposition B). Role User is the observed teacher: it can only DENY create/edit/delete/evaluator-sign and restrict reads to the caller's own teacher record. Its only non-restrictive effect is self-service read of the caller's OWN teacher record (observations page/history still sit behind the observations.view route rule), so it is not a cross-user bypass; a grant of the create/edit/delete/sign keys to role User is inert by design (segregation of duties). Reviewed in the Phase 3 audit; no Owner decision is outstanding."),
    ("role_constant", "saas/demo_lifecycle_service.py"): ("IDENTITY", 1, "Finds platform owner recipients."),
    ("role_constant", "saas/demo_notification_service.py"): ("IDENTITY", 1, "Finds platform owner recipients."),
    ("role_constant", "saas/provisioning_service.py"): ("HELPER", 2, "Provisions the initial tenant Administrator account."),
    ("role_constant", "talent_local_test_data.py"): ("HELPER", 2, "Local-only Talent test data seeding."),
    # --- role literals ----------------------------------------------------
    ("role_literal", "auth.py"): ("HELPER", 5, "Role normalisation aliases and legacy Developer value."),
    ("role_literal", "db_migrations.py"): ("HELPER", 3, "Migration of legacy role values."),
    ("role_literal", "routers/observations.py"): ("LEGACY", 1, "Display label map (rating '1': Limited); not a role check."),
    ("role_literal", "saas/router.py"): ("LEGACY", 4, "Audit actor_role label 'Platform Owner' on platform-owner-guarded admin actions."),
    # --- is_admin-style flags ----------------------------------------------
    # --- platform identity ---------------------------------------------------
    ("platform_identity", "auth.py"): ("HELPER", 23, "Canonical identity helpers and resolver."),
    ("platform_identity", "authorization.py"): ("HELPER", 1, "Commercial-access bypass for platform users."),
    ("platform_identity", "main.py"): ("IDENTITY", 36, "Platform-console/scope routes, tenant-vs-platform target selection; combined with permission keys where capability-governed."),
    ("platform_identity", "ui_shell.py"): ("IDENTITY", 2, "Shell context: no demo banner / design-studio only for platform users."),
    ("platform_identity", "routers/users.py"): ("IDENTITY", 5, "Target scope selection (platform actor uses the TARGET user's school)."),
    ("platform_identity", "saas/ai_entitlement_service.py"): ("IDENTITY", 1, "Platform bypass in AI entitlement."),
    ("platform_identity", "saas/demo_access_service.py"): ("IDENTITY", 1, "Platform bypass in demo access."),
    ("platform_identity", "saas/demo_operations_service.py"): ("IDENTITY", 1, "Platform-only demo operations."),
    ("platform_identity", "saas/draft_lifecycle_service.py"): ("IDENTITY", 2, "Platform-only lifecycle actions."),
    ("platform_identity", "saas/existing_workspace_conversion_service.py"): ("IDENTITY", 1, "Platform-only conversion."),
    ("platform_identity", "saas/orphaned_test_account_service.py"): ("IDENTITY", 2, "Platform-only purge."),
    ("platform_identity", "saas/promo_code_service.py"): ("IDENTITY", 2, "Platform-only promo management (plus promo_codes.* keys)."),
    ("platform_identity", "saas/router.py"): ("IDENTITY", 7, "Platform-only SaaS admin guards."),
    ("platform_identity", "saas/promo_redemption_service.py"): ("IDENTITY", 1, "Service-layer defense in depth for platform promo grant replacement: platform identity AND promo_codes.manage, the same decision as saas.router._require_promo_permission; it only narrows access and grants nothing."),
    ("platform_identity", "talent_request_permissions.py"): ("HELPER", 1, "Request-scoped memo of auth.has_permission for Talent routes: mirrors its exact decision order (empty key True, inactive False, platform Owner True, else membership in the canonical auth.get_allowed_permission_keys set including per-user overrides per ADR 0040); no role shortcut, created per request, never cached across requests or users."),
    # --- raw RolePermission access outside role_permission_service -----------
    ("raw_role_permission", "auth.py"): ("HELPER", 0, "Removed: dead duplicate raw reader deleted in the Phase 3 audit."),
    ("raw_role_permission", "models.py"): ("HELPER", 1, "ORM model definition."),
    ("raw_role_permission", "main.py"): ("HELPER", 2, "Startup table creation and a docstring; no raw query remains."),
    ("raw_role_permission", "role_permission_service.py"): ("HELPER", 12, "The sole role-policy service."),
    ("raw_role_permission", "user_permission_service.py"): ("HELPER", 1, "Docstring reference."),
    ("raw_role_permission", "saas/workspace_analysis_service.py"): ("HELPER", 1, "Tenant workspace analysis row count (read-only)."),
    ("raw_role_permission", "saas/workspace_deletion_service.py"): ("HELPER", 2, "Tenant workspace purge of that tenant's rows."),
    # --- raw UserPermissionOverride ----------------------------------------
    ("raw_user_override", "models.py"): ("HELPER", 1, "ORM model definition."),
    ("raw_user_override", "main.py"): ("HELPER", 1, "Startup table creation."),
    ("raw_user_override", "user_permission_service.py"): ("HELPER", 7, "The sole per-user exception service."),
    # --- SchoolGroup id from form/query ------------------------------------
    ("form_school_group_id", "saas/router.py"): ("IDENTITY", 2, "Promo grant replacement (GET Query, POST Form): both handlers first require _require_promo_permission (platform identity AND promo_codes.manage) and the service re-checks the same and resolves the organization by id; a platform actor may target any tenant by design, and no tenant actor can reach these routes."),
    ("form_school_group_id", "main.py"): ("IDENTITY", 6, "Every use re-checks: tenant actors are forced to their own SchoolGroup; only platform actors (with the all-school capability) may target another (role-permissions, logos, create_branch, open-academic-year, /scope/organization)."),
    # --- per-request snapshot attributes ------------------------------------
    ("orm_permission_stash", "auth.py"): ("LEGACY", 1, "Per-request frozen snapshot on the user instance built by get_current_user; never read as authority (no reader exists)."),
    ("orm_permission_stash", "ui_shell.py"): ("LEGACY", 1, "Per-render snapshot for templates; never read as authority."),
    # --- lru_cache: unrelated reference data ---------------------------------
    ("lru_cache", "location_service.py"): ("HELPER", 4, "Static country/region dataset cache; no permission state."),
    ("lru_cache", "saas/service.py"): ("HELPER", 2, "Static IANA timezone list; no permission state."),
}


def _scan():
    hits = collections.defaultdict(int)
    for path in support.non_test_python_files():
        rel = support._rel(path)
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    hits[(name, rel)] += 1
    return hits


def test_every_dangerous_pattern_hit_is_classified_with_its_exact_count():
    hits = _scan()
    unclassified = {k: v for k, v in hits.items() if k not in CLASSIFIED}
    assert unclassified == {}, f"New unclassified permission-shortcut hits: {unclassified}"
    changed = {
        key: (hits.get(key, 0), expected[1])
        for key, expected in CLASSIFIED.items()
        if hits.get(key, 0) != expected[1]
    }
    assert changed == {}, f"Hit counts changed (review and reclassify): {changed}"


def test_only_accepted_classes_are_allowlisted_and_reasons_exist():
    for key, (klass, _count, reason) in CLASSIFIED.items():
        assert klass in ACCEPTED, key
        assert reason.strip(), key


def test_no_module_level_permission_cache_or_persisted_snapshot():
    hits = _scan()
    assert [k for k in hits if k[0] == "module_permission_cache"] == []


def test_raw_policy_queries_live_only_in_their_services():
    """RolePermission/UserPermissionOverride are queried only by the two services;
    other files may only define, create tables, purge a tenant or count rows."""
    import ast

    allowed_query_files = {"role_permission_service.py", "user_permission_service.py"}
    offenders = []
    for path in support.non_test_python_files():
        rel = support._rel(path)
        if rel in allowed_query_files or rel == "models.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "query":
                for arg in node.args:
                    if getattr(arg, "attr", "") in {"RolePermission", "UserPermissionOverride"}:
                        offenders.append((rel, node.lineno))
    # tenant-scoped analysis count / purge are the only reviewed exceptions
    assert {rel for rel, _ in offenders} <= {
        "saas/workspace_analysis_service.py",
        "saas/workspace_deletion_service.py",
    }, offenders


def test_templates_never_authorise_by_role_name():
    role_gate = re.compile(r"{%-?\s*(?:if|elif)\b[^%]*\b(?:role|effective_role|platform_role)\b[^%]*(?:==|!=|\bin\b)\s*['\"]")
    offenders = []
    for path in support.template_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in role_gate.finditer(text):
            offenders.append((support._rel(path), match.group(0)[:80]))
    assert offenders == [], offenders


def test_class_counts_are_reportable():
    counts = collections.Counter(klass for klass, _c, _r in CLASSIFIED.values())
    assert set(counts) <= ACCEPTED
    assert "ESCALATE" not in counts
