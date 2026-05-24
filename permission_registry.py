import auth


MANAGED_ROLES = (
    auth.ROLE_DEVELOPER,
    auth.ROLE_ADMINISTRATOR,
    auth.ROLE_USER,
    auth.ROLE_LIMITED,
)


PERMISSION_GROUPS = (
    {
        "key": "dashboard",
        "label": "Dashboard",
        "permissions": (
            ("dashboard.view", "View dashboard"),
            ("dashboard.view_branch_summary", "View branch summary"),
            ("dashboard.view_reports", "View dashboard reports"),
            ("dashboard.export_reports", "Export dashboard reports"),
            ("dashboard.view_all_schools", "View all-school dashboard"),
        ),
    },
    {
        "key": "users",
        "label": "Users",
        "permissions": (
            ("users.view", "View users"),
            ("users.create", "Create users"),
            ("users.edit_profile", "Edit user profile"),
            ("users.assign_position", "Assign position"),
            ("users.assign_role", "Assign role"),
            ("users.assign_developer_role", "Assign Developer role"),
            ("users.assign_branch", "Assign branch"),
            ("users.activate_deactivate", "Activate/deactivate users"),
            ("users.reset_password", "Reset user password"),
            ("users.delete", "Delete users"),
            ("users.bulk_delete", "Bulk delete users"),
            ("users.manage_profile_photo", "Manage profile photo"),
            ("users.manage_developer_accounts", "Manage Developer accounts"),
        ),
    },
    {
        "key": "teachers",
        "label": "Teachers",
        "permissions": (
            ("teachers.view", "View teachers"),
            ("teachers.create", "Create teachers"),
            ("teachers.edit", "Edit teachers"),
            ("teachers.delete", "Delete teachers"),
            ("teachers.bulk_delete", "Bulk delete teachers"),
            ("teachers.assign_subjects", "Assign teacher subjects"),
            ("teachers.manage_qualifications", "Manage teacher qualifications"),
            ("teachers.manage_capacity", "Manage capacity and extra hours"),
            ("teachers.copy_year_data", "Copy teachers between years"),
            ("teachers.import", "Import teacher data"),
            ("teachers.export", "Export teacher data"),
        ),
    },
    {
        "key": "subjects",
        "label": "Subjects",
        "permissions": (
            ("subjects.view", "View subjects"),
            ("subjects.create", "Create subjects"),
            ("subjects.edit", "Edit subjects"),
            ("subjects.delete", "Delete subjects"),
            ("subjects.copy_year_data", "Copy subjects between years"),
            ("subjects.manage_colors", "Manage subject colors"),
            ("subjects.import", "Import subjects"),
            ("subjects.export", "Export subjects"),
        ),
    },
    {
        "key": "planning",
        "label": "Planning",
        "permissions": (
            ("planning.view", "View planning"),
            ("planning.create_section", "Create planning sections"),
            ("planning.edit_section", "Edit planning sections"),
            ("planning.delete_section", "Delete planning sections"),
            ("planning.assign_teacher", "Assign teachers to sections"),
            ("planning.manage_homeroom", "Manage homeroom ownership"),
            ("planning.copy_year_data", "Copy planning between years"),
            ("planning.import", "Import planning data"),
            ("planning.export", "Export planning"),
        ),
    },
    {
        "key": "timetable",
        "label": "Timetable",
        "permissions": (
            ("timetable.view", "View timetable"),
            ("timetable.create", "Create timetable entries"),
            ("timetable.edit", "Edit timetable entries"),
            ("timetable.delete", "Delete timetable entries"),
            ("timetable.manage_blocks", "Manage non-teaching blocks"),
            ("timetable.manage_settings", "Manage timetable settings"),
            ("timetable.publish", "Publish timetable"),
            ("timetable.export", "Export timetable"),
        ),
    },
    {
        "key": "academic_calendar",
        "label": "Academic Calendar",
        "permissions": (
            ("calendar.view", "View academic calendar"),
            ("calendar.create", "Create calendar events"),
            ("calendar.edit", "Edit calendar events"),
            ("calendar.delete", "Delete calendar events"),
            ("calendar.assign_targets", "Assign event targets"),
            ("calendar.manage_event_types", "Manage event types"),
            ("calendar.send_notifications", "Send event notifications"),
            ("calendar.export", "Export calendar"),
        ),
    },
    {
        "key": "observations",
        "label": "Observations",
        "permissions": (
            ("observations.view", "View observations"),
            ("observations.create_formal", "Create formal observations"),
            ("observations.create_non_formal", "Create non-formal observations"),
            ("observations.edit_draft", "Edit observation drafts"),
            ("observations.submit", "Submit observations"),
            ("observations.delete", "Delete observations"),
            ("observations.sign_evaluator", "Evaluator signature"),
            ("observations.sign_teacher", "Teacher signature"),
            ("observations.self_evaluate", "Complete teacher self-evaluation"),
            ("observations.unlock", "Unlock locked observations"),
            ("observations.view_reports", "View observation reports"),
            ("observations.export_reports", "Export observation reports"),
            ("observations.manage_templates", "Manage rubric templates"),
        ),
    },
    {
        "key": "notifications",
        "label": "Notifications",
        "permissions": (
            ("notifications.view", "View notifications"),
            ("notifications.send_direct", "Send direct messages"),
            ("notifications.broadcast", "Broadcast messages"),
            ("notifications.resolve", "Resolve notifications"),
        ),
    },
    {
        "key": "school_management",
        "label": "School Management",
        "permissions": (
            ("schools.view", "View school management"),
            ("schools.create", "Create schools"),
            ("schools.edit", "Edit school information"),
            ("schools.delete", "Delete schools"),
            ("schools.manage_all_schools", "Manage all schools"),
            ("branches.create", "Create branches"),
            ("branches.edit", "Edit branches"),
            ("branches.activate_deactivate", "Activate/deactivate branches"),
            ("branches.delete", "Delete branches"),
            ("academic_years.create", "Create academic years"),
            ("academic_years.activate", "Set current academic year"),
            ("branding.manage_school_logos", "Manage school logos"),
            ("branding.manage_branch_logos", "Manage branch logo overrides"),
        ),
    },
    {
        "key": "configuration",
        "label": "System Configuration",
        "permissions": (
            ("configuration.view", "View configuration"),
            ("configuration.manage_permissions", "Manage role permissions"),
            ("configuration.manage_degrees", "Manage degree options"),
            ("configuration.manage_specializations", "Manage specialization options"),
            ("configuration.view_audit_log", "View audit log"),
            ("configuration.export_audit_log", "Export audit log"),
            ("configuration.manage_global_defaults", "Manage global configuration defaults"),
        ),
    },
    {
        "key": "system_owner",
        "label": "System Owner",
        "permissions": (
            ("system_owner.full_access", "Full system owner access"),
            ("system_owner.switch_all_schools", "Switch into any school"),
            ("system_owner.manage_subscriptions", "Manage SaaS subscriptions"),
            ("system_owner.create_subscription_school", "Create school from subscription"),
            ("system_owner.manage_global_role_permissions", "Manage global role permissions"),
            ("system_owner.manage_developer_accounts", "Manage Developer accounts"),
            ("system_owner.run_startup_repairs", "Run startup/schema repairs"),
            ("system_owner.view_cross_school_audit", "View cross-school audit"),
            ("system_owner.export_cross_school_data", "Export cross-school data"),
        ),
    },
)


PERMISSION_LABELS = {
    permission_key: permission_label
    for group in PERMISSION_GROUPS
    for permission_key, permission_label in group["permissions"]
}


ALL_PERMISSION_KEYS = tuple(PERMISSION_LABELS.keys())


DEVELOPER_ONLY_PERMISSION_KEYS = {
    "dashboard.view_all_schools",
    "users.assign_developer_role",
    "users.manage_developer_accounts",
    "schools.manage_all_schools",
    "configuration.export_audit_log",
    "configuration.manage_global_defaults",
    "system_owner.full_access",
    "system_owner.switch_all_schools",
    "system_owner.manage_subscriptions",
    "system_owner.create_subscription_school",
    "system_owner.manage_global_role_permissions",
    "system_owner.manage_developer_accounts",
    "system_owner.run_startup_repairs",
    "system_owner.view_cross_school_audit",
    "system_owner.export_cross_school_data",
}


DEFAULT_ROLE_PERMISSIONS = {
    auth.ROLE_DEVELOPER: set(ALL_PERMISSION_KEYS),
    auth.ROLE_ADMINISTRATOR: {
        key
        for key in ALL_PERMISSION_KEYS
        if key not in DEVELOPER_ONLY_PERMISSION_KEYS
        and not key.startswith("schools.delete")
    },
    auth.ROLE_USER: {
        "dashboard.view",
        "dashboard.view_branch_summary",
        "subjects.view",
        "teachers.view",
        "planning.view",
        "planning.create_section",
        "planning.edit_section",
        "timetable.view",
        "calendar.view",
        "calendar.create",
        "calendar.edit",
        "observations.view",
        "observations.create_formal",
        "observations.create_non_formal",
        "observations.edit_draft",
        "observations.submit",
        "observations.sign_evaluator",
        "observations.sign_teacher",
        "observations.self_evaluate",
        "notifications.view",
    },
    auth.ROLE_LIMITED: {
        "dashboard.view",
        "subjects.view",
        "teachers.view",
        "planning.view",
        "timetable.view",
        "calendar.view",
        "observations.view",
        "notifications.view",
    },
}


def normalize_managed_role(role: str) -> str:
    normalized = auth.normalize_role(role)
    return normalized if normalized in MANAGED_ROLES else ""


def get_default_permissions_for_role(role: str) -> set[str]:
    normalized = normalize_managed_role(role)
    if not normalized:
        return set()
    if normalized == auth.ROLE_DEVELOPER:
        return set(ALL_PERMISSION_KEYS)
    return set(DEFAULT_ROLE_PERMISSIONS.get(normalized, set())) - DEVELOPER_ONLY_PERMISSION_KEYS


def build_role_permission_payload(role: str, allowed_keys: set[str] | None = None) -> dict:
    normalized = normalize_managed_role(role)
    allowed = set(allowed_keys or get_default_permissions_for_role(normalized))
    if normalized != auth.ROLE_DEVELOPER:
        allowed -= DEVELOPER_ONLY_PERMISSION_KEYS
    groups = []
    for group in PERMISSION_GROUPS:
        permissions = []
        for permission_key, permission_label in group["permissions"]:
            developer_only = permission_key in DEVELOPER_ONLY_PERMISSION_KEYS
            permissions.append(
                {
                    "key": permission_key,
                    "label": permission_label,
                    "developer_only": developer_only,
                    "assignable": normalized == auth.ROLE_DEVELOPER or not developer_only,
                    "allowed": permission_key in allowed,
                }
            )
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "permissions": permissions,
                "allowed_count": sum(1 for item in permissions if item["allowed"]),
                "total_count": len(permissions),
            }
        )
    return {
        "role": normalized,
        "allowed_keys": sorted(allowed),
        "allowed_count": len(allowed),
        "total_count": len(ALL_PERMISSION_KEYS),
        "groups": groups,
    }
