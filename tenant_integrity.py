from sqlalchemy import func

import models


def _count(query) -> int:
    return int(query.scalar() or 0)


def _add_issue(issues: list[dict], key: str, count: int, description: str, severity: str = "critical"):
    if count:
        issues.append(
            {
                "key": key,
                "count": int(count),
                "severity": severity,
                "description": description,
            }
        )


def _table_count(db, model, *filters) -> int:
    query = db.query(func.count(model.id))
    for filter_clause in filters:
        query = query.filter(filter_clause)
    return _count(query)


def _missing_reference_count(db, model, reference_model, source_column):
    return _count(
        db.query(func.count(model.id))
        .outerjoin(reference_model, source_column == reference_model.id)
        .filter(source_column.isnot(None), reference_model.id.is_(None))
    )


def _scope_group_mismatch_count(db, model):
    return _count(
        db.query(func.count(model.id))
        .join(models.Branch, model.branch_id == models.Branch.id)
        .join(models.AcademicYear, model.academic_year_id == models.AcademicYear.id)
        .filter(models.Branch.school_group_id != models.AcademicYear.school_group_id)
    )


def collect_tenant_integrity_issues(db) -> list[dict]:
    issues = []

    _add_issue(
        issues,
        "branches_missing_school_group",
        _table_count(db, models.Branch, models.Branch.school_group_id.is_(None)),
        "Branches must belong to a school group.",
    )
    _add_issue(
        issues,
        "academic_years_missing_school_group",
        _table_count(db, models.AcademicYear, models.AcademicYear.school_group_id.is_(None)),
        "Academic years must belong to a school group.",
    )
    _add_issue(
        issues,
        "users_missing_school_group",
        _table_count(db, models.User, models.User.school_group_id.is_(None)),
        "Users must belong to a school group.",
    )
    _add_issue(
        issues,
        "users_missing_branch",
        _table_count(db, models.User, models.User.branch_id.is_(None)),
        "Users must have a branch assignment.",
    )
    _add_issue(
        issues,
        "users_missing_academic_year",
        _table_count(db, models.User, models.User.academic_year_id.is_(None)),
        "Users must have an academic year assignment.",
    )
    _add_issue(
        issues,
        "users_branch_missing",
        _missing_reference_count(db, models.User, models.Branch, models.User.branch_id),
        "Users reference a branch that does not exist.",
    )
    _add_issue(
        issues,
        "users_academic_year_missing",
        _missing_reference_count(db, models.User, models.AcademicYear, models.User.academic_year_id),
        "Users reference an academic year that does not exist.",
    )
    _add_issue(
        issues,
        "users_school_group_missing",
        _missing_reference_count(db, models.User, models.SchoolGroup, models.User.school_group_id),
        "Users reference a school group that does not exist.",
    )
    _add_issue(
        issues,
        "users_branch_school_group_mismatch",
        _count(
            db.query(func.count(models.User.id))
            .join(models.Branch, models.User.branch_id == models.Branch.id)
            .filter(models.User.school_group_id != models.Branch.school_group_id)
        ),
        "User school_group_id must match the assigned branch school group.",
    )

    scoped_models = [
        ("subjects", models.Subject),
        ("teachers", models.Teacher),
        ("planning_sections", models.PlanningSection),
        ("observations", models.Observation),
        ("calendar_events", models.CalendarEvent),
        ("timetable_entries", models.TimetableEntry),
        ("hiring_plan_drafts", models.HiringPlanDraft),
    ]
    for table_key, model in scoped_models:
        _add_issue(
            issues,
            f"{table_key}_branch_missing",
            _missing_reference_count(db, model, models.Branch, model.branch_id),
            f"{table_key} rows reference a branch that does not exist.",
        )
        _add_issue(
            issues,
            f"{table_key}_academic_year_missing",
            _missing_reference_count(db, model, models.AcademicYear, model.academic_year_id),
            f"{table_key} rows reference an academic year that does not exist.",
        )
        _add_issue(
            issues,
            f"{table_key}_branch_year_group_mismatch",
            _scope_group_mismatch_count(db, model),
            f"{table_key} rows mix a branch and academic year from different school groups.",
        )

    _add_issue(
        issues,
        "notifications_missing_school_group",
        _table_count(db, models.SystemNotification, models.SystemNotification.school_group_id.is_(None)),
        "System notifications must be tenant-scoped.",
    )
    _add_issue(
        issues,
        "notifications_school_group_missing",
        _missing_reference_count(
            db,
            models.SystemNotification,
            models.SchoolGroup,
            models.SystemNotification.school_group_id,
        ),
        "System notifications reference a school group that does not exist.",
    )
    _add_issue(
        issues,
        "notifications_recipient_missing",
        _count(
            db.query(func.count(models.SystemNotification.id))
            .outerjoin(models.User, models.SystemNotification.recipient_user_id == models.User.user_id)
            .filter(models.User.id.is_(None))
        ),
        "System notifications reference a recipient user that does not exist.",
    )
    _add_issue(
        issues,
        "notifications_branch_year_group_mismatch",
        _count(
            db.query(func.count(models.SystemNotification.id))
            .join(models.Branch, models.SystemNotification.branch_id == models.Branch.id)
            .join(models.AcademicYear, models.SystemNotification.academic_year_id == models.AcademicYear.id)
            .filter(models.Branch.school_group_id != models.AcademicYear.school_group_id)
        ),
        "System notifications mix a branch and academic year from different school groups.",
    )

    return issues


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        issues = collect_tenant_integrity_issues(db)
        if not issues:
            print("No tenant integrity issues found.")
        for issue in issues:
            print(f"{issue['severity']} {issue['key']} count={issue['count']}: {issue['description']}")
    finally:
        db.close()
