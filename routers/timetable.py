from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
from dependencies import get_db
from timetable_logic import (
    build_timetable_workspace_payload,
    get_scope_ids,
    normalize_day_key,
)
from ui_shell import build_shell_context


router = APIRouter(prefix="/timetable", tags=["Timetable"])
templates = Jinja2Templates(directory="templates")


def _parse_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _get_current_user_or_redirect(request: Request, db: Session):
    current_user = auth.get_current_user(request, db)
    if not current_user:
        return None, RedirectResponse(url="/", status_code=302)
    return current_user, None


def _find_section_by_id(workspace_payload: dict, section_id: int):
    return next(
        (
            section
            for section in workspace_payload.get("sections", [])
            if int(section.get("id") or 0) == int(section_id or 0)
        ),
        None,
    )


def _find_teacher_by_id(workspace_payload: dict, teacher_id: int):
    return next(
        (
            teacher
            for teacher in workspace_payload.get("teachers", [])
            if int(teacher.get("id") or 0) == int(teacher_id or 0)
        ),
        None,
    )


def _find_entry_by_section_slot(
    workspace_payload: dict,
    *,
    section_id: int,
    day_key: str,
    period_index: int,
):
    return next(
        (
            entry
            for entry in workspace_payload.get("entries", [])
            if int(entry.get("section_id") or 0) == int(section_id or 0)
            and str(entry.get("day_key") or "") == day_key
            and int(entry.get("period_index") or 0) == int(period_index or 0)
        ),
        None,
    )


def _find_section_option(
    workspace_payload: dict,
    *,
    section_id: int,
    subject_code: str,
):
    section_payload = _find_section_by_id(workspace_payload, section_id)
    if not section_payload:
        return None
    return next(
        (
            option
            for option in section_payload.get("options", [])
            if str(option.get("subject_code") or "").strip().upper() == subject_code
        ),
        None,
    )


def _find_teacher_conflict(
    workspace_payload: dict,
    *,
    teacher_id: int,
    day_key: str,
    period_index: int,
    ignore_entry_id: int | None = None,
):
    return next(
        (
            entry
            for entry in workspace_payload.get("entries", [])
            if int(entry.get("teacher_id") or 0) == int(teacher_id or 0)
            and str(entry.get("day_key") or "") == day_key
            and int(entry.get("period_index") or 0) == int(period_index or 0)
            and int(entry.get("id") or 0) != int(ignore_entry_id or 0)
        ),
        None,
    )


def _json_error(message: str, status_code: int = 400):
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "message": message,
        },
    )


def _json_success(workspace_payload: dict, *, message: str = ""):
    return JSONResponse(
        content={
            "ok": True,
            "message": message,
            "payload": workspace_payload,
        }
    )


@router.get("/")
def timetable_page(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return redirect_response

    branch_id, academic_year_id = get_scope_ids(current_user)
    workspace_payload = build_timetable_workspace_payload(
        db,
        branch_id,
        academic_year_id,
    )

    return templates.TemplateResponse(
        request,
        "timetable.html",
        {
            "request": request,
            "timetable_payload": workspace_payload,
            "can_edit_timetable": auth.can_edit_data(current_user),
            "can_manage_system_settings": auth.can_manage_system_settings(current_user),
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="timetable",
                title="Timetable",
                intro=(
                    "Build the weekly teaching schedule from your current branch planning, "
                    "teacher assignments, and timetable settings."
                ),
                icon="timetable",
            ),
        },
    )


@router.post("/api/assign")
async def assign_timetable_slot(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return _json_error("Please sign in again to continue.", status_code=401)

    if not auth.can_edit_data(current_user):
        return _json_error(
            "Your role can view the timetable but cannot change timetable slots.",
            status_code=403,
        )

    try:
        payload = await request.json()
    except Exception:
        return _json_error("Unable to read the timetable request payload.")

    branch_id, academic_year_id = get_scope_ids(current_user)
    workspace_payload = build_timetable_workspace_payload(
        db,
        branch_id,
        academic_year_id,
    )
    settings_payload = workspace_payload.get("settings", {})

    section_id = _parse_int(payload.get("section_id"))
    period_index = _parse_int(payload.get("period_index"))
    day_key = normalize_day_key(payload.get("day_key"))
    subject_code = str(payload.get("subject_code") or "").strip().upper()

    if section_id is None:
        return _json_error("Select a valid section before assigning a timetable slot.")
    if not day_key or day_key not in {
        day_item.get("key")
        for day_item in workspace_payload.get("days", [])
    }:
        return _json_error("Selected timetable day is not valid for the current settings.")
    if (
        period_index is None
        or period_index <= 0
        or period_index > int(settings_payload.get("periods_per_day") or 0)
    ):
        return _json_error("Selected timetable period is outside the configured school day.")
    if any(
        str(block_slot.get("day_key") or "") == day_key
        and int(block_slot.get("period_index") or 0) == period_index
        for block_slot in workspace_payload.get("blocked_slots", [])
    ):
        return _json_error("That slot is blocked by a break, prayer time, or another non-teaching rule.")

    section_payload = _find_section_by_id(workspace_payload, section_id)
    if not section_payload:
        return _json_error("Selected section is not available in the active planning scope.")

    existing_entry_payload = _find_entry_by_section_slot(
        workspace_payload,
        section_id=section_id,
        day_key=day_key,
        period_index=period_index,
    )
    existing_entry_row = None
    if existing_entry_payload and existing_entry_payload.get("id"):
        existing_entry_row = db.query(models.TimetableEntry).filter(
            models.TimetableEntry.id == int(existing_entry_payload["id"]),
            models.TimetableEntry.branch_id == branch_id,
            models.TimetableEntry.academic_year_id == academic_year_id,
        ).first()

    if not subject_code:
        if not existing_entry_row:
            return _json_error("That slot is already empty.")
        db.delete(existing_entry_row)
        db.commit()
        refreshed_payload = build_timetable_workspace_payload(db, branch_id, academic_year_id)
        return _json_success(refreshed_payload, message="Timetable slot cleared.")

    option_payload = _find_section_option(
        workspace_payload,
        section_id=section_id,
        subject_code=subject_code,
    )
    if not option_payload:
        return _json_error("Selected subject is not part of this section timetable plan.")
    if not option_payload.get("is_schedulable") or not option_payload.get("teacher_id"):
        return _json_error(
            "This subject does not currently have an assigned teacher in planning, so it cannot be placed yet."
        )

    teacher_id = int(option_payload["teacher_id"])
    teacher_payload = _find_teacher_by_id(workspace_payload, teacher_id)
    if not teacher_payload:
        return _json_error("Assigned teacher is not available in the active branch and academic year.")

    other_entry_for_teacher = _find_teacher_conflict(
        workspace_payload,
        teacher_id=teacher_id,
        day_key=day_key,
        period_index=period_index,
        ignore_entry_id=existing_entry_payload.get("id") if existing_entry_payload else None,
    )
    if other_entry_for_teacher:
        return _json_error(
            f"{teacher_payload['teacher_name']} is already teaching "
            f"{other_entry_for_teacher.get('section_label', 'another section')} in that slot."
        )

    scheduled_count = sum(
        1
        for entry in workspace_payload.get("entries", [])
        if int(entry.get("section_id") or 0) == section_id
        and str(entry.get("subject_code") or "").strip().upper() == subject_code
        and str(entry.get("status") or "") == "scheduled"
        and int(entry.get("id") or 0) != int(existing_entry_payload.get("id") or 0)
    )
    weekly_hours = int(option_payload.get("weekly_hours") or 0)
    if scheduled_count >= weekly_hours:
        return _json_error(
            f"{subject_code} already reached its required {weekly_hours} hour"
            + ("" if weekly_hours == 1 else "s")
            + f" for {section_payload['section_label']}."
        )

    try:
        if existing_entry_row is None:
            db.add(
                models.TimetableEntry(
                    branch_id=branch_id,
                    academic_year_id=academic_year_id,
                    planning_section_id=section_id,
                    subject_code=subject_code,
                    teacher_id=teacher_id,
                    day_key=day_key,
                    period_index=period_index,
                )
            )
        else:
            existing_entry_row.subject_code = subject_code
            existing_entry_row.teacher_id = teacher_id
            existing_entry_row.day_key = day_key
            existing_entry_row.period_index = period_index
        db.commit()
    except IntegrityError:
        db.rollback()
        return _json_error(
            "This slot could not be saved because it conflicts with another timetable entry. Refresh the timetable and try again."
        )

    refreshed_payload = build_timetable_workspace_payload(db, branch_id, academic_year_id)
    return _json_success(
        refreshed_payload,
        message=(
            f"{subject_code} assigned to {section_payload['section_label']} "
            f"with {teacher_payload['teacher_name']}."
        ),
    )
