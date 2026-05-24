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
            ("users.assign_branch", "Assign branch"),
            ("users.activate_deactivate", "Activate/deactivate users"),
            ("users.reset_password", "Reset user password"),
            ("users.delete", "Delete users"),
            ("users.bulk_delete", "Bulk delete users"),
            ("users.manage_profile_photo", "Manage profile photo"),
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
        ),
    },
)


PERMISSION_LABELS = {
    permission_key: permission_label
    for group in PERMISSION_GROUPS
    for permission_key, permission_label in group["permissions"]
}


ALL_PERMISSION_KEYS = tuple(PERMISSION_LABELS.keys())


DEFAULT_ROLE_PERMISSIONS = {
    auth.ROLE_DEVELOPER: set(ALL_PERMISSION_KEYS),
    auth.ROLE_ADMINISTRATOR: {
        key
        for key in ALL_PERMISSION_KEYS
        if not key.startswith("schools.delete")
        and not key.startswith("configuration.export_audit_log")
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
    return set(DEFAULT_ROLE_PERMISSIONS.get(normalized, set()))


def build_role_permission_payload(role: str, allowed_keys: set[str] | None = None) -> dict:
    normalized = normalize_managed_role(role)
    allowed = set(allowed_keys or get_default_permissions_for_role(normalized))
    groups = []
    for group in PERMISSION_GROUPS:
        permissions = []
        for permission_key, permission_label in group["permissions"]:
            permissions.append(
                {
                    "key": permission_key,
                    "label": permission_label,
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
