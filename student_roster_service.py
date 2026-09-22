"""Bounded Student roster import/export backend (M6, first release).

Scope decisions made explicit here (see docs/PROJECT_STATE.md M6 entry for
the governed record):

- .xlsx only, via ``openpyxl`` (already a repository dependency), following
  the existing ``routers/subjects.py`` import/export convention
  (``load_workbook(..., data_only=True)`` for safe formula handling,
  ``StreamingResponse`` for export).
- Import is CREATE-ONLY for this first release: every row enrolls a NEW
  Student with an initial Academic Placement. Updating an existing Student's
  identity/placement through the roster file is explicitly out of scope for
  M6 and is not attempted here - this keeps the bounded roster service from
  duplicating ``student_academic_service``'s update/correction semantics and
  avoids inventing merge/overwrite rules the KMS does not authorize.
- No persistent import-job/batch table: preview is a stateless, zero-mutation
  read; apply re-parses/revalidates the same uploaded workbook and performs
  one atomic all-or-nothing write.
- Canonical matching identity only: Branch/Academic Year are matched by their
  governed identity (``Branch.name`` within the tenant, ``AcademicYear.year_name``
  within the tenant); Grade/Section are matched via ``normalize_grade_level``
  and canonical ``PlanningSection.section_name`` - never the ADR 0045
  presentation-only ``section_display`` label, even for the Al-Andalus
  workspace.
- The managed TIS Student number (ADR 0043/M2) invariants - canonicalization,
  10-digit business input, global uniqueness, privacy-safe conflict
  disclosure - are never duplicated here; every write goes through
  ``student_academic_service.create_student_with_number`` and every conflict
  check goes through ``student_academic_service.describe_student_number_conflict``.
"""
from __future__ import annotations

import os
from datetime import datetime

from openpyxl import Workbook, load_workbook
from sqlalchemy.exc import IntegrityError

import auth
import models
from academic_grade import format_section_display, normalize_grade_level
from student_academic_service import (
    StudentAcademicError,
    create_placement,
    create_student_with_number,
    current_student_number,
    describe_student_number_conflict,
    list_students,
    resolve_placement,
    update_student,
    validate_student_number_digits,
)

# File-safety bounds. No existing repository-wide upload-size/row-count
# convention was found (see M6 preflight); these are this feature's own
# explicit, documented judgment call.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 2000

REQUIRED_COLUMNS = (
    "student_id", "first_name", "last_name", "branch", "academic_year", "grade", "section",
)
OPTIONAL_COLUMNS = ("father_name", "gender", "status")
ROSTER_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

# Reuses the exact UI-canonical gender convention already offered by the
# Student form/profile (``routers/students_ui.py::GENDER_OPTIONS``). The
# service layer itself places no enum constraint on ``Student.gender``, but
# the roster import is a bulk-authoring surface, not a free-text field, so it
# is bound to the same values already presented to a human editor.
GENDER_OPTIONS = {"Male", "Female"}
STATUS_OPTIONS = {"active", "inactive"}

EXPORT_HEADERS = (
    "student_id", "first_name", "father_name", "last_name", "gender", "status",
    "branch", "academic_year", "grade", "section", "section_display",
)


def _row_error(row, field, error_code, message):
    return {"row": row, "field": field, "error_code": error_code, "safe_message": message}


def _file_error(error_code, message):
    return {"row": None, "field": None, "error_code": error_code, "safe_message": message}


def _norm_text(value):
    return " ".join(str(value or "").strip().split()).lower()


def _cell_text(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _cell_student_id(value):
    """Normalize a Student-ID cell to a bare 10-digit string, or ``None`` if unusable.

    Handles both a safely preserved text cell (the exported/template form)
    and a cell Excel coerced to a number (leading zeros already lost by
    Excel itself before this ever reads it - nothing recovers that data).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return str(int(value))
    return _cell_text(value)


class RosterFileError(Exception):
    def __init__(self, error):
        super().__init__(error["safe_message"])
        self.error = error


def _open_workbook(upload):
    filename = str(getattr(upload, "filename", "") or "")
    if not filename.lower().endswith(".xlsx"):
        raise RosterFileError(_file_error("invalid_extension", "Only .xlsx workbooks are supported."))

    raw = upload.file
    raw.seek(0, os.SEEK_END)
    size = raw.tell()
    raw.seek(0)
    if size == 0:
        raise RosterFileError(_file_error("empty_file", "The uploaded file is empty."))
    if size > MAX_UPLOAD_BYTES:
        raise RosterFileError(_file_error(
            "file_too_large",
            f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload limit.",
        ))
    try:
        # data_only=True: any formula cell is read as its last-calculated
        # cached value, never evaluated here. keep_links=False: external
        # workbook links are dropped rather than followed.
        workbook = load_workbook(raw, data_only=True, keep_links=False)
    except Exception:
        raise RosterFileError(_file_error(
            "workbook_unreadable", "Unable to read the workbook. Use the exported roster format.",
        ))
    sheet = workbook.active
    if sheet is None or sheet.max_row < 1:
        raise RosterFileError(_file_error("workbook_unreadable", "The workbook has no readable rows."))
    return sheet


def _validate_headers(sheet):
    header_cells = list(sheet[1])
    positions = {}
    duplicates = set()
    for idx, cell in enumerate(header_cells, start=1):
        raw = cell.value
        if raw is None or str(raw).strip() == "":
            continue
        name = "_".join(str(raw).strip().lower().split())
        if name in positions:
            duplicates.add(name)
            continue
        positions[name] = idx
    if duplicates:
        raise RosterFileError(_file_error(
            "duplicate_column", f"Duplicate column(s): {', '.join(sorted(duplicates))}.",
        ))
    missing = [c for c in REQUIRED_COLUMNS if c not in positions]
    if missing:
        raise RosterFileError(_file_error(
            "missing_required_column", f"Missing required column(s): {', '.join(missing)}.",
        ))
    unexpected = sorted(c for c in positions if c not in ROSTER_COLUMNS)
    if unexpected:
        raise RosterFileError(_file_error(
            "unexpected_column", f"Unexpected column(s): {', '.join(unexpected)}.",
        ))
    return positions


def _row_values(sheet, positions, row_number):
    return {name: sheet.cell(row=row_number, column=col).value for name, col in positions.items()}


def _branch_lookup(db, school_group_id):
    lookup = {}
    for row in db.query(models.Branch).filter(models.Branch.school_group_id == school_group_id).all():
        lookup.setdefault(_norm_text(row.name), []).append(row)
    return lookup


def _year_lookup(db, school_group_id):
    lookup = {}
    for row in db.query(models.AcademicYear).filter(models.AcademicYear.school_group_id == school_group_id).all():
        lookup.setdefault(_norm_text(row.year_name), []).append(row)
    return lookup


def _resolve_row(db, *, school_group_id, actor, row_number, values, branches, years, seen_ids):
    errors = []

    student_id_raw = _cell_student_id(values.get("student_id"))
    canonical_value = None
    if not student_id_raw:
        errors.append(_row_error(row_number, "student_id", "missing_value", "Student ID is required."))
    else:
        try:
            validate_student_number_digits(student_id_raw)
        except StudentAcademicError:
            errors.append(_row_error(
                row_number, "student_id", "invalid_student_id",
                "Student ID must be exactly 10 digits (leading zeros preserved).",
            ))
        else:
            canonical_value = f"STD{student_id_raw}"
            if canonical_value in seen_ids:
                errors.append(_row_error(
                    row_number, "student_id", "duplicate_student_id_in_file",
                    "This Student ID appears more than once in the workbook.",
                ))
            seen_ids.add(canonical_value)

    first_name = _cell_text(values.get("first_name"))
    if not first_name:
        errors.append(_row_error(row_number, "first_name", "missing_value", "First name is required."))
    elif len(first_name) > 100:
        errors.append(_row_error(row_number, "first_name", "invalid_field", "First name is too long."))

    last_name = _cell_text(values.get("last_name"))
    if not last_name:
        errors.append(_row_error(row_number, "last_name", "missing_value", "Last name is required."))
    elif len(last_name) > 100:
        errors.append(_row_error(row_number, "last_name", "invalid_field", "Last name is too long."))

    father_name = _cell_text(values.get("father_name")) or None
    if father_name and len(father_name) > 100:
        errors.append(_row_error(row_number, "father_name", "invalid_field", "Father name is too long."))

    gender_raw = _cell_text(values.get("gender"))
    gender = gender_raw or None
    if gender_raw and gender_raw not in GENDER_OPTIONS:
        errors.append(_row_error(row_number, "gender", "invalid_field", "Gender must be Male or Female."))

    status_raw = _cell_text(values.get("status")).lower()
    status = status_raw or "active"
    if status_raw and status_raw not in STATUS_OPTIONS:
        errors.append(_row_error(row_number, "status", "invalid_field", "Status must be active or inactive."))

    branch_name = _cell_text(values.get("branch"))
    branch = None
    if not branch_name:
        errors.append(_row_error(row_number, "branch", "missing_value", "Branch is required."))
    else:
        candidates = branches.get(_norm_text(branch_name), [])
        if len(candidates) == 0:
            errors.append(_row_error(row_number, "branch", "invalid_branch", "Branch was not found."))
        elif len(candidates) > 1:
            errors.append(_row_error(row_number, "branch", "ambiguous_reference", "Branch reference is ambiguous."))
        else:
            branch = candidates[0]
            if not auth.can_access_all_branches(actor) and not auth.can_access_branch(db, actor, branch.id):
                errors.append(_row_error(
                    row_number, "branch", "unauthorized_reference", "Branch is outside your authorized scope.",
                ))
                branch = None

    year_name = _cell_text(values.get("academic_year"))
    year = None
    if not year_name:
        errors.append(_row_error(row_number, "academic_year", "missing_value", "Academic Year is required."))
    else:
        candidates = years.get(_norm_text(year_name), [])
        if len(candidates) == 0:
            errors.append(_row_error(row_number, "academic_year", "invalid_academic_year", "Academic Year was not found."))
        elif len(candidates) > 1:
            errors.append(_row_error(row_number, "academic_year", "ambiguous_reference", "Academic Year reference is ambiguous."))
        else:
            year = candidates[0]

    grade_raw = _cell_text(values.get("grade"))
    grade_level = normalize_grade_level(grade_raw) if grade_raw else ""
    if not grade_raw:
        errors.append(_row_error(row_number, "grade", "missing_value", "Grade is required."))
    elif not grade_level:
        errors.append(_row_error(row_number, "grade", "invalid_grade", "Grade is not a recognized grade level."))

    section_name = _cell_text(values.get("section"))
    if not section_name:
        errors.append(_row_error(row_number, "section", "missing_value", "Section is required."))

    planning_section = None
    if branch is not None and year is not None and grade_level and section_name:
        candidates = db.query(models.PlanningSection).filter_by(
            branch_id=branch.id, academic_year_id=year.id,
            grade_level=grade_level, section_name=section_name,
        ).all()
        if len(candidates) == 0:
            errors.append(_row_error(
                row_number, "section", "invalid_section",
                "Section was not found for the given Branch, Academic Year, and Grade.",
            ))
        elif len(candidates) > 1:
            errors.append(_row_error(row_number, "section", "ambiguous_reference", "Section reference is ambiguous."))
        else:
            planning_section = candidates[0]

    conflict = None
    if canonical_value and not errors:
        conflict = describe_student_number_conflict(
            db, requester_school_group_id=school_group_id, actor=actor, canonical_value=canonical_value,
        )
        if not conflict.get("available", True):
            detail = {"row": row_number, "field": "student_id", "error_code": "student_id_conflict",
                       "safe_message": "That Student ID is unavailable."}
            if conflict.get("student_id") is not None:
                detail["student_id"] = conflict["student_id"]
                detail["display_name"] = conflict["display_name"]
            errors.append(detail)

    if errors:
        return {"row": row_number, "status": "error", "errors": errors}

    return {
        "row": row_number,
        "status": "ok",
        "data": {
            "student_number": student_id_raw,
            "first_name": first_name,
            "father_name": father_name,
            "last_name": last_name,
            "gender": gender,
            "status": status,
            "branch_id": branch.id,
            "branch_name": branch.name,
            "academic_year_id": year.id,
            "academic_year_name": year.year_name,
            "grade_level": grade_level,
            "section_name": section_name,
            "planning_section_id": planning_section.id if planning_section else None,
        },
    }


def _validate_workbook(db, *, school_group_id, actor, upload):
    """Shared, stateless (zero-mutation) parse+validate core for preview AND apply.

    Every call re-reads the actual uploaded workbook bytes; nothing here
    trusts or accepts a previously computed preview result as input, and
    nothing here writes to the database.
    """
    sheet = _open_workbook(upload)
    positions = _validate_headers(sheet)

    data_row_count = sheet.max_row - 1
    if data_row_count > MAX_DATA_ROWS:
        raise RosterFileError(_file_error(
            "too_many_rows", f"Workbook exceeds the {MAX_DATA_ROWS}-row import limit.",
        ))

    branches = _branch_lookup(db, school_group_id)
    years = _year_lookup(db, school_group_id)

    rows = []
    seen_ids = set()
    for row_number in range(2, sheet.max_row + 1):
        values = _row_values(sheet, positions, row_number)
        if all(v is None or str(v).strip() == "" for v in values.values()):
            continue
        rows.append(_resolve_row(
            db, school_group_id=school_group_id, actor=actor, row_number=row_number,
            values=values, branches=branches, years=years, seen_ids=seen_ids,
        ))
    return rows


def preview_roster(db, *, school_group_id, actor, upload):
    """Stateless preview: parses, validates, and resolves references. No DB writes."""
    try:
        rows = _validate_workbook(db, school_group_id=school_group_id, actor=actor, upload=upload)
    except RosterFileError as exc:
        return {"status": "rejected", "file_error": exc.error, "rows": [], "summary": _summary([])}
    return {"status": "ok", "file_error": None, "rows": rows, "summary": _summary(rows)}


def _summary(rows):
    valid = sum(1 for r in rows if r["status"] == "ok")
    return {"total_rows": len(rows), "valid_rows": valid, "error_rows": len(rows) - valid}


def apply_roster(db, *, school_group_id, actor, upload):
    """Revalidates the freshly uploaded workbook (never trusts a client-submitted
    preview payload) and applies it atomically: any row failure - including a
    fresh conflict discovered only at apply time - rolls back the entire apply
    with no partial Student/Placement writes.
    """
    try:
        rows = _validate_workbook(db, school_group_id=school_group_id, actor=actor, upload=upload)
    except RosterFileError as exc:
        return {"status": "rejected", "file_error": exc.error, "rows": [], "summary": _summary([]), "applied": False}

    if not rows:
        return {
            "status": "rejected", "file_error": _file_error("empty_workbook", "No data rows were found to import."),
            "rows": [], "summary": _summary([]), "applied": False,
        }

    if any(row["status"] == "error" for row in rows):
        return {"status": "rejected", "file_error": None, "rows": rows, "summary": _summary(rows), "applied": False}

    now = datetime.utcnow()
    created_student_ids = []
    try:
        for row in rows:
            data = row["data"]
            student = create_student_with_number(
                db, school_group_id=school_group_id, student_number=data["student_number"],
                first_name=data["first_name"], father_name=data["father_name"], last_name=data["last_name"],
                gender=data["gender"], actor=actor,
            )
            if data["status"] == "inactive":
                update_student(db, school_group_id=school_group_id, student_id=student.id, actor=actor, status="inactive")
            create_placement(
                db, school_group_id=school_group_id, student_id=student.id,
                academic_year_id=data["academic_year_id"], branch_id=data["branch_id"],
                planning_section_id=data["planning_section_id"], grade_level=data["grade_level"],
                section_name=data["section_name"], effective_from=now, actor=actor,
            )
            created_student_ids.append(student.id)
    except Exception as exc:
        db.rollback()
        row_number = rows[len(created_student_ids)]["row"] if len(created_student_ids) < len(rows) else None
        if isinstance(exc, StudentAcademicError):
            message, code = exc.message, exc.code
        elif isinstance(exc, IntegrityError):
            # The service layer never commits/catches this itself (ADR 0043/M2):
            # a race means another writer claimed the same Student ID between
            # preview/revalidation and this apply's insert. Never leak the raw
            # IntegrityError text.
            message, code = "That Student ID became unavailable during apply.", "student_id_conflict"
        else:
            message, code = "Apply-time revalidation failed.", "apply_write_failed"
        failure = _row_error(row_number, None, code, message)
        annotated_rows = [
            {"row": r["row"], "status": "error", "errors": [failure]} if r["row"] == row_number else r
            for r in rows
        ]
        return {
            "status": "rejected", "file_error": None,
            "rows": annotated_rows,
            "summary": _summary(annotated_rows), "applied": False,
        }

    db.commit()
    return {
        "status": "ok", "file_error": None, "rows": rows, "summary": _summary(rows),
        "applied": True, "created_student_ids": created_student_ids,
    }


def export_roster(db, *, school_group_id, actor):
    """Build the .xlsx roster export workbook for authorized Students only.

    Tenant-isolated by ``school_group_id``. Branch-restricted actors (not
    ``auth.can_access_all_branches``) only see Students whose CURRENT
    effective Academic Placement Branch is in their accessible-Branch set -
    a legacy/unplaced Student, or one currently placed outside the actor's
    Branch scope, is simply omitted from a Branch-restricted export, mirroring
    the existing granular Branch-gating already applied to placement data in
    ``routers/students_ui.py``. Student ID is written as a canonical
    ``STD``-prefixed TEXT cell (never a number) so Excel never strips leading
    zeros or applies scientific notation; a legacy Student with no managed
    Student number gets a blank cell, never a fabricated one.
    """
    org_scope = auth.can_access_all_branches(actor)
    accessible_ids = None
    if not org_scope:
        accessible_ids = {
            row[0] for row in auth.get_accessible_branch_query(db, actor).with_entities(models.Branch.id).all()
        }

    workspace = db.get(models.SchoolGroup, school_group_id)
    workspace_uuid = workspace.workspace_uuid if workspace else None

    now = datetime.utcnow()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Roster"
    sheet.append(list(EXPORT_HEADERS))
    for col_idx in range(1, len(EXPORT_HEADERS) + 1):
        sheet.cell(row=1, column=col_idx).number_format = "@"

    for student in list_students(db, school_group_id=school_group_id):
        placement = resolve_placement(db, school_group_id=school_group_id, student_id=student.id, at=now)
        if not org_scope:
            if placement is None or placement.branch_id not in accessible_ids:
                continue
        student_number = current_student_number(db, school_group_id=school_group_id, student_id=student.id) or ""
        branch_name = ""
        grade_level = ""
        section_name = ""
        section_display = ""
        academic_year_name = ""
        if placement is not None:
            branch = db.get(models.Branch, placement.branch_id)
            branch_name = branch.name if branch else ""
            year = db.get(models.AcademicYear, placement.academic_year_id)
            academic_year_name = year.year_name if year else ""
            grade_level = placement.grade_level
            section_name = placement.section_name
            section_display = format_section_display(workspace_uuid, grade_level, section_name)

        row_index = sheet.max_row + 1
        row_values = [
            student_number, student.first_name, student.father_name or "", student.last_name,
            student.gender or "", student.status, branch_name, academic_year_name,
            grade_level, section_name, section_display,
        ]
        sheet.append(row_values)
        # Student ID column stays a text cell even when the value is blank
        # (legacy Student with no managed number) or purely numeric digits.
        sheet.cell(row=row_index, column=1).number_format = "@"
        sheet.cell(row=row_index, column=1).value = student_number

    return workbook
