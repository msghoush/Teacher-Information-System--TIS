from __future__ import annotations

import calendar
import html
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
from dependencies import get_db
from subject_colors import build_subject_theme, normalize_hex_color
from ui_shell import build_shell_context


router = APIRouter(tags=["Academic Calendar"])
templates = Jinja2Templates(directory="templates")

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
STATIC_DIR = Path("static")
CALENDAR_PDF_LOGOS = (
    STATIC_DIR / "images" / "TIS_Logo_Adjusted.png",
    STATIC_DIR / "images" / "andalus-logo-main.png",
    STATIC_DIR / "images" / "cognia-logo.png",
)

DEFAULT_EVENT_TYPES = (
    {
        "name": "Assessment",
        "color": "#2563EB",
        "icon": "clipboard-check",
    },
    {
        "name": "Quiz",
        "color": "#7C3AED",
        "icon": "check-circle",
    },
    {
        "name": "Exam",
        "color": "#DC2626",
        "icon": "exam",
    },
    {
        "name": "Vacation / Holiday",
        "color": "#0EA5E9",
        "icon": "home",
    },
    {
        "name": "Extracurricular Activity",
        "color": "#16A34A",
        "icon": "activity",
    },
    {
        "name": "School Event",
        "color": "#0F766E",
        "icon": "calendar",
    },
    {
        "name": "Meeting",
        "color": "#F59E0B",
        "icon": "meeting",
    },
    {
        "name": "PLC / Professional Learning Community",
        "color": "#8B5CF6",
        "icon": "teachers",
    },
    {
        "name": "Deadline",
        "color": "#EA580C",
        "icon": "deadline",
    },
    {
        "name": "Classroom Visit",
        "color": "#0891B2",
        "icon": "visit",
    },
    {
        "name": "Parent Meeting",
        "color": "#DB2777",
        "icon": "parent",
    },
    {
        "name": "Administrative Task",
        "color": "#475569",
        "icon": "task",
    },
    {
        "name": "Other",
        "color": "#64748B",
        "icon": "info",
    },
)

CALENDAR_MANAGE_ROLES = {
    auth.ROLE_DEVELOPER,
    auth.ROLE_ADMINISTRATOR,
    auth.ROLE_EDITOR,
}
EVENT_STATUS_OPTIONS = ("Planned", "Confirmed", "In Progress", "Completed", "Cancelled")
PRIORITY_OPTIONS = ("Low", "Normal", "High", "Urgent")
TARGET_GROUP_OPTIONS = ("All School", "Grade", "Section", "Teacher", "Role", "Custom")
RECURRENCE_OPTIONS = ("None", "Daily", "Weekly", "Monthly", "Yearly")
ALL_GRADES_VALUE = "All Grades"
ALL_GRADES_ALIASES = {"ALL", "ALL GRADE", "ALL GRADES", "ALL_GRADES"}
GRADE_OPTIONS = ["KG"] + [str(value) for value in range(1, 13)]
TARGET_GRADE_OPTIONS = [ALL_GRADES_VALUE] + GRADE_OPTIONS
ALL_SECTIONS_VALUE = "__all_sections__"
ALL_SECTIONS_LABEL = "All Sections"
ALL_SECTIONS_ALIASES = {
    ALL_SECTIONS_VALUE.upper(),
    "ALL",
    "ALL SECTION",
    "ALL SECTIONS",
    "ALL_SECTIONS",
}
ICON_OPTIONS = (
    "calendar",
    "clipboard-check",
    "check-circle",
    "exam",
    "vacation",
    "home",
    "activity",
    "meeting",
    "teachers",
    "deadline",
    "visit",
    "parent",
    "task",
    "warning",
    "settings",
    "info",
)
CONFIGURATION_MODULES = (
    {
        "key": "overview",
        "label": "Overview",
        "href": "/system-configuration",
        "icon": "settings",
        "description": "Open the configuration hub.",
    },
    {
        "key": "branches",
        "label": "Branches",
        "href": "/system-configuration/branches",
        "icon": "branch",
        "description": "Manage branch records and status.",
    },
    {
        "key": "users",
        "label": "Users",
        "href": "/users",
        "icon": "users",
        "description": "Manage user accounts, roles, and active status.",
    },
    {
        "key": "degrees",
        "label": "Degrees",
        "href": "/system-configuration/degrees",
        "icon": "copy",
        "description": "Manage academic degree options.",
    },
    {
        "key": "specializations",
        "label": "Specializations",
        "href": "/system-configuration/specializations",
        "icon": "subjects",
        "description": "Manage majors and teaching specializations.",
    },
    {
        "key": "academic-years",
        "label": "Academic Years",
        "href": "/system-configuration/academic-years",
        "icon": "year",
        "description": "Open and switch live academic years.",
    },
    {
        "key": "timetable-settings",
        "label": "Timetable Settings",
        "href": "/system-configuration/timetable-settings",
        "icon": "timetable",
        "description": "Define the school week, periods, and non-teaching timetable blocks.",
    },
    {
        "key": "academic-calendar",
        "label": "Academic Calendar",
        "href": "/system-configuration/calendar",
        "icon": "calendar",
        "description": "Configure calendar event types, colors, and icons for the active scope.",
    },
)


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


def _normalize_spaces(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_date(value) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if not DATE_PATTERN.match(cleaned):
        return ""
    try:
        datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError:
        return ""
    return cleaned


def _normalize_time(value) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if not TIME_PATTERN.match(cleaned):
        return ""
    hours, minutes = cleaned.split(":", 1)
    if 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59:
        return cleaned
    return ""


def _format_date_label(value: str) -> str:
    parsed = _date_from_iso(value)
    if not parsed:
        return value or ""
    return parsed.strftime("%A, %d %B %Y")


def _event_end_date_value(event) -> str:
    start_value = _normalize_date(getattr(event, "event_date", "") or "")
    end_value = _normalize_date(getattr(event, "end_date", "") or "")
    if not start_value:
        return end_value
    if not end_value or end_value < start_value:
        return start_value
    return end_value


def _build_date_range_label(start_value: str, end_value: str) -> str:
    normalized_start = _normalize_date(start_value)
    normalized_end = _normalize_date(end_value) or normalized_start
    if not normalized_start:
        return ""
    if normalized_end <= normalized_start:
        return _format_date_label(normalized_start)
    return f"{_format_date_label(normalized_start)} - {_format_date_label(normalized_end)}"


def _build_date_badge_label(start_value: str, end_value: str) -> str:
    start_date = _date_from_iso(start_value)
    end_date = _date_from_iso(end_value)
    if not start_date:
        return ""
    if not end_date or end_date <= start_date:
        return f"{start_date.day:02d}"
    if start_date.month == end_date.month and start_date.year == end_date.year:
        return f"{start_date.day:02d}-{end_date.day:02d}"
    return f"{start_date.day:02d}+"


def _calculate_duration_days(start_value: str, end_value: str) -> int:
    start_date = _date_from_iso(start_value)
    end_date = _date_from_iso(end_value)
    if not start_date:
        return 0
    if not end_date or end_date < start_date:
        return 1
    return (end_date - start_date).days + 1


def _date_from_iso(value: str) -> date | None:
    normalized = _normalize_date(value)
    if not normalized:
        return None
    return datetime.strptime(normalized, "%Y-%m-%d").date()


def _normalize_month(value: str) -> date:
    cleaned = str(value or "").strip()
    if cleaned:
        try:
            parsed = datetime.strptime(cleaned, "%Y-%m").date()
            return parsed.replace(day=1)
        except ValueError:
            pass
    return date.today().replace(day=1)


def _month_bounds(month_start: date) -> tuple[str, str]:
    _, last_day = calendar.monthrange(month_start.year, month_start.month)
    return (
        month_start.isoformat(),
        month_start.replace(day=last_day).isoformat(),
    )


def _month_link_value(month_start: date, offset: int) -> str:
    month_index = month_start.month - 1 + offset
    year = month_start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1).strftime("%Y-%m")


def _safe_redirect_path(value: str, default: str = "/academic-calendar/") -> str:
    cleaned = str(value or "").strip()
    if not cleaned or not cleaned.startswith("/") or cleaned.startswith("//"):
        return default
    return cleaned


def _pdf_escape_text(value: Any) -> str:
    text_value = str(value if value is not None else "")
    text_value = (
        text_value.replace("\u2022", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00d7", "x")
    )
    text_value = text_value.encode("latin-1", "replace").decode("latin-1")
    return text_value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_rgb(color_value: str, fallback: str = "#0A4EA3") -> tuple[float, float, float]:
    cleaned = str(color_value or fallback).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", cleaned):
        cleaned = str(fallback).strip().lstrip("#")
    return (
        int(cleaned[0:2], 16) / 255,
        int(cleaned[2:4], 16) / 255,
        int(cleaned[4:6], 16) / 255,
    )


def _text_luminance(color_value: str) -> float:
    r, g, b = _pdf_rgb(color_value, "#FFFFFF")
    return (0.299 * r) + (0.587 * g) + (0.114 * b)


def _pdf_text_color_for(fill_color: str) -> str:
    return "#FFFFFF" if _text_luminance(fill_color) < 0.58 else "#11243F"


def _wrap_pdf_text(value: Any, max_chars: int, max_lines: int | None = None) -> list[str]:
    words = str(value or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
            if max_lines and len(lines) >= max_lines:
                break
        else:
            current = candidate
    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)
    if max_lines and len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = f"{lines[-1][: max(0, max_chars - 3)].rstrip()}..."
    return lines


def _icon_label(icon_name: str, type_name: str = "") -> str:
    icon = str(icon_name or "").strip().lower()
    labels = {
        "calendar": "CL",
        "clipboard-check": "AS",
        "check-circle": "QZ",
        "exam": "EX",
        "vacation": "VH",
        "home": "HO",
        "activity": "AC",
        "meeting": "MT",
        "teachers": "PL",
        "deadline": "DL",
        "visit": "VS",
        "parent": "PA",
        "task": "TK",
        "warning": "!",
        "info": "IN",
    }
    if icon in labels:
        return labels[icon]
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", str(type_name or "EV"))
    return (cleaned[:2] or "EV").upper()


def _status_color(status: str) -> str:
    return {
        "Planned": "#0A4EA3",
        "Confirmed": "#174EA6",
        "In Progress": "#C47A00",
        "Completed": "#176B35",
        "Cancelled": "#9F2D1F",
    }.get(str(status or ""), "#64748B")


class _CalendarPdfReport:
    width = 595.28
    height = 841.89
    margin = 38

    def __init__(self, title: str, subtitle: str, logos: tuple[Path, ...] = ()):
        self.title = title
        self.subtitle = subtitle
        self.logos = tuple(logos or ())
        self.pages: list[list[str]] = []
        self.images: dict[str, dict[str, Any]] = {}
        self.y = self.height - self.margin
        self.add_page()

    def _current(self) -> list[str]:
        return self.pages[-1]

    def _text_command(
        self,
        x: float,
        y: float,
        value: Any,
        size: float = 9,
        color: str = "#11243F",
        bold: bool = False,
    ) -> str:
        r, g, b = _pdf_rgb(color, "#11243F")
        font = "/F2" if bold else "/F1"
        return (
            f"{r:.4f} {g:.4f} {b:.4f} rg\n"
            f"BT {font} {size:.2f} Tf {x:.2f} {y:.2f} Td ({_pdf_escape_text(value)}) Tj ET\n"
        )

    def add_page(self):
        self.pages.append([])
        self.y = self.height - self.margin
        self.text(self.margin, self.y, self.title, size=16, color="#0A4EA3", bold=True)
        self.y -= 15
        self.text(self.margin, self.y, self.subtitle, size=8, color="#536782")
        logo_x = self.width - self.margin
        for logo_path in reversed(self.logos):
            image_size = self._image_size(logo_path)
            if not image_size:
                continue
            image_width, image_height = image_size
            target_height = 27
            target_width = max(22, min(92, target_height * (image_width / max(image_height, 1))))
            logo_x -= target_width
            self.image(logo_path, logo_x, self.height - self.margin - 9, target_width, target_height)
            logo_x -= 8
        self.y -= 18
        self.line(self.margin, self.y, self.width - self.margin, self.y, "#CAD9EA")
        self.y -= 18

    def _register_image(self, path: Path) -> dict[str, Any] | None:
        image_path = Path(path)
        key = str(image_path.resolve()) if image_path.exists() else str(image_path)
        if key in self.images:
            return self.images[key]
        if not image_path.exists():
            return None
        try:
            with Image.open(image_path) as raw_image:
                image = raw_image.convert("RGBA")
                background = Image.new("RGBA", image.size, (255, 255, 255, 255))
                background.alpha_composite(image)
                rgb_image = background.convert("RGB")
                rgb_image.thumbnail((900, 260), Image.LANCZOS)
                buffer = BytesIO()
                rgb_image.save(buffer, format="JPEG", quality=88, optimize=True)
                record = {
                    "name": f"Im{len(self.images) + 1}",
                    "data": buffer.getvalue(),
                    "width": rgb_image.width,
                    "height": rgb_image.height,
                }
        except Exception:
            return None
        self.images[key] = record
        return record

    def _image_size(self, path: Path) -> tuple[int, int] | None:
        record = self._register_image(path)
        if not record:
            return None
        return int(record["width"]), int(record["height"])

    def image(self, path: Path, x: float, y: float, width: float, height: float):
        record = self._register_image(path)
        if not record:
            return
        self._current().append(
            f"q {width:.2f} 0 0 {height:.2f} {x:.2f} {y:.2f} cm /{record['name']} Do Q\n"
        )

    def ensure_space(self, height: float):
        if self.y - height < self.margin + 28:
            self.add_page()

    def text(
        self,
        x: float,
        y: float,
        value: Any,
        size: float = 9,
        color: str = "#11243F",
        bold: bool = False,
    ):
        self._current().append(self._text_command(x, y, value, size=size, color=color, bold=bold))

    def rect(self, x: float, y: float, width: float, height: float, fill: str, stroke: str | None = None):
        r, g, b = _pdf_rgb(fill)
        command = f"{r:.4f} {g:.4f} {b:.4f} rg\n{x:.2f} {y:.2f} {width:.2f} {height:.2f} re f\n"
        if stroke:
            sr, sg, sb = _pdf_rgb(stroke, "#CAD9EA")
            command += (
                f"{sr:.4f} {sg:.4f} {sb:.4f} RG\n0.7 w\n"
                f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re S\n"
            )
        self._current().append(command)

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str = "#CAD9EA", width: float = 0.8):
        r, g, b = _pdf_rgb(color, "#CAD9EA")
        self._current().append(
            f"{r:.4f} {g:.4f} {b:.4f} RG\n{width:.2f} w\n{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S\n"
        )

    def heading(self, value: str):
        self.ensure_space(34)
        self.text(self.margin, self.y, value, size=13, color="#0A4EA3", bold=True)
        self.y -= 18

    def paragraph(self, value: str, width: float = 500, size: float = 8.5, color: str = "#536782"):
        max_chars = max(24, int(width / (size * 0.46)))
        for line in _wrap_pdf_text(value, max_chars):
            self.ensure_space(12)
            self.text(self.margin, self.y, line, size=size, color=color)
            self.y -= 11
        self.y -= 3

    def badge(self, x: float, y: float, label: str, color: str, width: float = 46, height: float = 16):
        self.rect(x, y, width, height, color)
        self.text(x + 5, y + 5, label[:18], size=6.6, color=_pdf_text_color_for(color), bold=True)

    def kpi_grid(self, cards: list[tuple[str, str, str, str]]):
        if not cards:
            return
        card_width = (self.width - (2 * self.margin) - 18) / 4
        card_height = 52
        for index, (label, value, note, color) in enumerate(cards):
            if index % 4 == 0:
                self.ensure_space(card_height + 12)
                row_y = self.y - card_height
            x = self.margin + (index % 4) * (card_width + 6)
            self.rect(x, row_y, card_width, card_height, "#F8FBFF", "#D8E5F4")
            self.rect(x, row_y, 5, card_height, color)
            self.text(x + 10, row_y + 34, label, size=7, color="#536782", bold=True)
            self.text(x + 10, row_y + 17, value, size=14, color=color, bold=True)
            self.text(x + 10, row_y + 6, note[:28], size=6.2, color="#536782")
            if index % 4 == 3:
                self.y = row_y - 12
        if len(cards) % 4:
            self.y = row_y - 12

    def event_card(self, event: dict):
        description_lines = _wrap_pdf_text(event.get("description", ""), 76, max_lines=2)
        card_height = 78 + (len(description_lines) * 10)
        self.ensure_space(card_height + 8)
        x = self.margin
        y = self.y - card_height
        width = self.width - (2 * self.margin)
        event_color = event.get("type_color", "#0A4EA3")
        self.rect(x, y, width, card_height, "#FFFFFF", "#D8E5F4")
        self.rect(x, y, 6, card_height, event_color)
        self.rect(x + 14, y + card_height - 38, 28, 28, event_color)
        self.text(
            x + 19,
            y + card_height - 27,
            _icon_label(event.get("type_icon", ""), event.get("type_name", "")),
            size=8,
            color=_pdf_text_color_for(event_color),
            bold=True,
        )
        title = str(event.get("title", "") or "Calendar Event")
        self.text(x + 50, y + card_height - 18, title[:62], size=10.5, color="#11243F", bold=True)
        self.badge(x + 50, y + card_height - 38, str(event.get("type_name", "Event"))[:24], event_color, width=94)
        status = str(event.get("status", "") or "Planned")
        self.badge(x + width - 88, y + card_height - 27, status[:16], _status_color(status), width=76, height=17)
        self.text(
            x + 50,
            y + card_height - 54,
            str(event.get("date_range_label", "") or ""),
            size=7.8,
            color="#17365D",
            bold=True,
        )
        self.text(
            x + 50,
            y + card_height - 67,
            f"{event.get('time_label', 'Time not set')} | {event.get('target_label', 'All School')}",
            size=7.5,
            color="#536782",
        )
        desc_y = y + card_height - 80
        for line in description_lines:
            self.text(x + 50, desc_y, line, size=7.2, color="#536782")
            desc_y -= 10
        self.y = y - 8

    def build(self) -> bytes:
        for index, page in enumerate(self.pages, start=1):
            page.append(
                self._text_command(
                    self.margin,
                    24,
                    f"Generated by TIS | Academic Calendar | Page {index}",
                    size=7,
                    color="#536782",
                )
            )
        image_objects: list[tuple[str, bytes]] = []
        for record in self.images.values():
            image_objects.append(
                (
                    record["name"],
                    (
                        b"<< /Type /XObject /Subtype /Image /Width "
                        + str(record["width"]).encode("ascii")
                        + b" /Height "
                        + str(record["height"]).encode("ascii")
                        + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
                        + str(len(record["data"])).encode("ascii")
                        + b" >>\nstream\n"
                        + record["data"]
                        + b"\nendstream"
                    ),
                )
            )
        content_streams = ["".join(page).encode("latin-1", "replace") for page in self.pages]
        objects: list[bytes] = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        ]
        image_object_numbers: dict[str, int] = {}
        for name, image_object in image_objects:
            image_object_numbers[name] = len(objects) + 1
            objects.append(image_object)

        kids: list[str] = []
        page_objects: list[bytes] = []
        for content in content_streams:
            page_number = len(objects) + len(page_objects) + 1
            content_number = page_number + 1
            kids.append(f"{page_number} 0 R")
            xobjects = " ".join(
                f"/{name} {object_number} 0 R"
                for name, object_number in image_object_numbers.items()
            )
            xobject_resource = f" /XObject << {xobjects} >>" if xobjects else ""
            page_objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.width:.2f} {self.height:.2f}] "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >>{xobject_resource} >> "
                    f"/Contents {content_number} 0 R >>"
                ).encode("latin-1")
            )
            page_objects.append(
                b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream"
            )
        objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode("latin-1")
        objects.extend(page_objects)

        pdf = b"%PDF-1.4\n"
        offsets = [0]
        for object_index, obj in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf += f"{object_index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
        xref_offset = len(pdf)
        pdf += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
        pdf += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            pdf += f"{offset:010d} 00000 n \n".encode("ascii")
        pdf += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
        return pdf


def _ensure_calendar_event_schema(db: Session) -> None:
    try:
        inspector = inspect(db.bind)
        table_names = set(inspector.get_table_names())
        if "calendar_events" not in table_names:
            return
        column_names = {
            column["name"]
            for column in inspector.get_columns("calendar_events")
        }
        if "end_date" not in column_names:
            db.execute(text("ALTER TABLE calendar_events ADD COLUMN end_date VARCHAR(10)"))
        db.execute(
            text(
                "UPDATE calendar_events "
                "SET end_date = event_date "
                "WHERE end_date IS NULL OR TRIM(end_date) = ''"
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _redirect_with_query(path: str, key: str, message: str) -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    return RedirectResponse(
        url=f"{path}{separator}{key}={quote_plus(message)}",
        status_code=303,
    )


def _get_current_user_or_redirect(request: Request, db: Session):
    current_user = auth.get_current_user(request, db)
    if not current_user:
        return None, RedirectResponse(url="/", status_code=302)
    return current_user, None


def _get_configuration_access(request: Request, db: Session):
    current_user = auth.get_current_user(request, db)
    if not current_user:
        return None, RedirectResponse(url="/", status_code=302)
    if not auth.can_manage_system_settings(current_user):
        return None, RedirectResponse(url="/dashboard", status_code=302)
    return current_user, None


def _get_scope_ids(current_user):
    return (
        getattr(current_user, "scope_branch_id", current_user.branch_id),
        getattr(current_user, "scope_academic_year_id", current_user.academic_year_id),
    )


def _can_manage_calendar(current_user) -> bool:
    role = auth.normalize_role(getattr(current_user, "role", ""))
    return role in CALENDAR_MANAGE_ROLES


def _get_configuration_modules(active_key: str) -> list[dict[str, object]]:
    return [
        {
            **module,
            "active": module["key"] == active_key,
        }
        for module in CONFIGURATION_MODULES
    ]


def _normalize_event_color(value: str) -> str:
    normalized = normalize_hex_color(value)
    return normalized or "#0A4EA3"


def _normalize_icon_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\-]+", "", str(value or "").strip().lower())
    return cleaned if cleaned in ICON_OPTIONS else "info"


def _normalize_choice(value: str, options, default: str) -> str:
    cleaned = _normalize_spaces(value)
    return cleaned if cleaned in options else default


def _is_checked(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _ensure_default_event_types(
    db: Session,
    branch_id: int,
    academic_year_id: int,
):
    existing_rows = db.query(models.CalendarEventType).filter(
        models.CalendarEventType.branch_id == branch_id,
        models.CalendarEventType.academic_year_id == academic_year_id,
    ).all()
    existing_names = {
        _normalize_spaces(row.name).lower()
        for row in existing_rows
        if _normalize_spaces(row.name)
    }
    existing_by_name = {
        _normalize_spaces(row.name).lower(): row
        for row in existing_rows
        if _normalize_spaces(row.name)
    }
    created_any = False
    updated_any = False
    for index, event_type in enumerate(DEFAULT_EVENT_TYPES, start=1):
        normalized_name = _normalize_spaces(event_type["name"])
        if normalized_name.lower() in existing_names:
            existing_row = existing_by_name.get(normalized_name.lower())
            if (
                existing_row
                and normalized_name.lower() == "vacation / holiday"
                and str(existing_row.icon or "").strip().lower() in {"", "vacation"}
            ):
                existing_row.icon = event_type["icon"]
                updated_any = True
            continue
        db.add(
            models.CalendarEventType(
                branch_id=branch_id,
                academic_year_id=academic_year_id,
                name=normalized_name,
                color=event_type["color"],
                icon=event_type["icon"],
                is_active=True,
                sort_order=index * 10,
            )
        )
        created_any = True
    if created_any or updated_any:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()


def _get_event_types(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    *,
    include_inactive: bool = False,
):
    query = db.query(models.CalendarEventType).filter(
        models.CalendarEventType.branch_id == branch_id,
        models.CalendarEventType.academic_year_id == academic_year_id,
    )
    if not include_inactive:
        query = query.filter(models.CalendarEventType.is_active == True)
    return query.order_by(
        models.CalendarEventType.sort_order.asc(),
        models.CalendarEventType.name.asc(),
    ).all()


def _build_teacher_display_name(teacher) -> str:
    parts = [
        getattr(teacher, "first_name", ""),
        getattr(teacher, "middle_name", ""),
        getattr(teacher, "last_name", ""),
    ]
    full_name = " ".join(part for part in parts if str(part or "").strip()).strip()
    return full_name or f"Teacher #{getattr(teacher, 'id', '')}"


def _build_user_display_name(user) -> str:
    parts = [
        getattr(user, "first_name", ""),
        getattr(user, "last_name", ""),
    ]
    full_name = " ".join(part for part in parts if str(part or "").strip()).strip()
    return full_name or getattr(user, "username", "") or getattr(user, "user_id", "") or "User"


def _get_scope_options(db: Session, branch_id: int, academic_year_id: int):
    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).order_by(
        models.Teacher.first_name.asc(),
        models.Teacher.last_name.asc(),
        models.Teacher.teacher_id.asc(),
    ).all()
    users = db.query(models.User).filter(
        models.User.is_active == True,
        models.User.branch_id == branch_id,
    ).order_by(
        models.User.first_name.asc(),
        models.User.last_name.asc(),
        models.User.username.asc(),
    ).all()
    sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).order_by(
        models.PlanningSection.grade_level.asc(),
        models.PlanningSection.section_name.asc(),
    ).all()
    return teachers, users, sections


def _build_section_label(section) -> str:
    if not section:
        return ""
    grade = str(getattr(section, "grade_level", "") or "").strip()
    section_name = str(getattr(section, "section_name", "") or "").strip()
    grade_label = "KG" if grade.upper() == "KG" else f"Grade {grade}"
    return f"{grade_label}-{section_name}" if section_name else grade_label


def _build_type_payload(event_type) -> dict:
    color = _normalize_event_color(getattr(event_type, "color", "") or "")
    theme = build_subject_theme(color)
    return {
        "id": event_type.id,
        "name": event_type.name,
        "color": color,
        "soft": theme["soft"],
        "surface": theme["surface"],
        "border": theme["border"],
        "text": theme["text"],
        "icon": _normalize_icon_name(getattr(event_type, "icon", "")),
        "is_active": bool(event_type.is_active),
        "sort_order": int(event_type.sort_order or 0),
    }


def _build_time_label(event) -> str:
    if bool(getattr(event, "all_day", False)):
        return "All day"
    start_time = str(getattr(event, "start_time", "") or "").strip()
    end_time = str(getattr(event, "end_time", "") or "").strip()
    if start_time and end_time:
        return f"{start_time} - {end_time}"
    if start_time:
        return start_time
    if end_time:
        return f"Until {end_time}"
    return "Time not set"


def _build_target_label(event, section_lookup, teacher_lookup) -> str:
    target_group = str(getattr(event, "target_group", "") or "All School").strip()
    if target_group == "All School":
        return "All School"
    if target_group == "Grade" and getattr(event, "target_grade", None):
        grade = str(event.target_grade)
        if grade.strip().upper() in ALL_GRADES_ALIASES:
            return ALL_GRADES_VALUE
        return "KG" if grade.upper() == "KG" else f"Grade {grade}"
    if target_group == "Section" and getattr(event, "target_section_id", None):
        return _build_section_label(section_lookup.get(event.target_section_id)) or "Section"
    if target_group == "Teacher" and getattr(event, "target_teacher_id", None):
        teacher = teacher_lookup.get(event.target_teacher_id)
        return _build_teacher_display_name(teacher) if teacher else "Teacher"
    if target_group == "Role" and getattr(event, "target_role", None):
        return str(event.target_role)
    if target_group == "Custom" and getattr(event, "target_role", None):
        return str(event.target_role)
    return target_group or "All School"


def _build_assignment_map(db: Session, event_ids, teacher_lookup, user_lookup):
    if not event_ids:
        return {}
    assignment_rows = db.query(models.CalendarEventAssignment).filter(
        models.CalendarEventAssignment.calendar_event_id.in_(event_ids)
    ).order_by(models.CalendarEventAssignment.id.asc()).all()
    assignments_by_event = defaultdict(
        lambda: {
            "teacher_ids": [],
            "user_ids": [],
            "labels": [],
            "rows": [],
        }
    )
    for assignment in assignment_rows:
        payload = assignments_by_event[assignment.calendar_event_id]
        row_payload = {
            "id": assignment.id,
            "teacher_id": assignment.teacher_id,
            "user_id": assignment.user_id,
            "assignment_role": assignment.assignment_role or "",
        }
        if assignment.teacher_id:
            teacher = teacher_lookup.get(assignment.teacher_id)
            if teacher:
                payload["teacher_ids"].append(assignment.teacher_id)
                payload["labels"].append(_build_teacher_display_name(teacher))
        if assignment.user_id:
            user = user_lookup.get(assignment.user_id)
            if user:
                payload["user_ids"].append(assignment.user_id)
                payload["labels"].append(_build_user_display_name(user))
        payload["rows"].append(row_payload)
    return assignments_by_event


def _serialize_event(
    event,
    *,
    type_lookup,
    section_lookup,
    teacher_lookup,
    assignment_payload,
):
    event_type = type_lookup.get(event.event_type_id)
    if event_type:
        type_payload = _build_type_payload(event_type)
    else:
        type_payload = {
            "id": None,
            "name": "Uncategorized",
            "color": "#64748B",
            "soft": "#F1F5F9",
            "surface": "#FFFFFF",
            "border": "#CBD5E1",
            "text": "#334155",
            "icon": "info",
            "is_active": True,
            "sort_order": 0,
        }
    labels = sorted(set(assignment_payload.get("labels", [])))
    assigned_summary = ", ".join(labels) if labels else "No assigned users"
    start_date_value = _normalize_date(event.event_date)
    end_date_value = _event_end_date_value(event)
    duration_days = _calculate_duration_days(start_date_value, end_date_value)
    target_group = event.target_group or "All School"
    target_grade = event.target_grade or (
        ALL_GRADES_VALUE if target_group == "All School" else ""
    )
    target_section_id = (
        ALL_SECTIONS_VALUE if target_group == "All School" else event.target_section_id
    )
    return {
        "id": event.id,
        "title": event.title,
        "event_type_id": event.event_type_id,
        "type_name": type_payload["name"],
        "type_color": type_payload["color"],
        "type_soft": type_payload["soft"],
        "type_surface": type_payload["surface"],
        "type_border": type_payload["border"],
        "type_text": type_payload["text"],
        "type_icon": type_payload["icon"],
        "event_date": start_date_value,
        "end_date": end_date_value,
        "date_label": _format_date_label(start_date_value),
        "end_date_label": _format_date_label(end_date_value),
        "date_range_label": _build_date_range_label(start_date_value, end_date_value),
        "date_badge_label": _build_date_badge_label(start_date_value, end_date_value),
        "duration_days": duration_days,
        "is_multi_day": duration_days > 1,
        "start_time": event.start_time or "",
        "end_time": event.end_time or "",
        "all_day": bool(event.all_day),
        "time_label": _build_time_label(event),
        "description": event.description or "",
        "target_group": target_group,
        "target_grade": target_grade,
        "target_section_id": target_section_id,
        "target_teacher_id": event.target_teacher_id,
        "target_role": event.target_role or "",
        "target_label": _build_target_label(event, section_lookup, teacher_lookup),
        "priority": event.priority or "Normal",
        "status": event.status or "Planned",
        "recurrence_rule": event.recurrence_rule or "None",
        "recurrence_interval": int(event.recurrence_interval or 1),
        "recurrence_until": event.recurrence_until or "",
        "assigned_teacher_ids": sorted(set(assignment_payload.get("teacher_ids", []))),
        "assigned_user_ids": sorted(set(assignment_payload.get("user_ids", []))),
        "assignment_labels": labels,
        "assignment_summary": assigned_summary,
    }


def _sort_event_payloads(event_payloads):
    return sorted(
        event_payloads,
        key=lambda event: (
            event["event_date"],
            "00:00" if event["all_day"] else event["start_time"] or "23:59",
            event["title"].lower(),
        ),
    )


def _build_month_grid(month_start: date, event_payloads):
    events_by_date = defaultdict(list)
    month_start_iso, month_end_iso = _month_bounds(month_start)
    month_end = _date_from_iso(month_end_iso)
    for event_payload in event_payloads:
        event_start = _date_from_iso(event_payload.get("event_date"))
        event_end = _date_from_iso(event_payload.get("end_date")) or event_start
        if not event_start:
            continue
        if not event_end or event_end < event_start:
            event_end = event_start
        visible_start = max(event_start, month_start)
        visible_end = min(event_end, month_end or event_end)
        if visible_start > visible_end:
            continue
        cursor = visible_start
        while cursor <= visible_end:
            occurrence = dict(event_payload)
            occurrence["occurrence_date"] = cursor.isoformat()
            if event_start == event_end:
                occurrence["occurrence_kind"] = "single"
            elif cursor == event_start:
                occurrence["occurrence_kind"] = "start"
            elif cursor == event_end:
                occurrence["occurrence_kind"] = "end"
            else:
                occurrence["occurrence_kind"] = "middle"
            events_by_date[cursor.isoformat()].append(occurrence)
            cursor += timedelta(days=1)

    today_iso = date.today().isoformat()
    weeks = []
    month_calendar = calendar.Calendar(firstweekday=6)
    for week in month_calendar.monthdatescalendar(month_start.year, month_start.month):
        week_payload = []
        for day_value in week:
            day_iso = day_value.isoformat()
            week_payload.append(
                {
                    "iso": day_iso,
                    "day_number": day_value.day,
                    "in_month": day_value.month == month_start.month,
                    "is_today": day_iso == today_iso,
                    "events": _sort_event_payloads(events_by_date.get(day_iso, [])),
                }
            )
        weeks.append(week_payload)
    return weeks


def _build_calendar_export_url(filters: dict, calendar_view: str) -> str:
    params = {
        "view": calendar_view,
        "month": filters.get("month", ""),
        "start_date": filters.get("start_date", ""),
        "end_date": filters.get("end_date", ""),
    }
    for key in (
        "event_type_id",
        "status",
        "priority",
        "grade",
        "section_id",
        "teacher_id",
        "user_id",
    ):
        value = filters.get(key)
        if value:
            params[key] = value
    return f"/academic-calendar/export.pdf?{urlencode(params)}"


def _calendar_report_period_label(filters: dict) -> str:
    start_label = _format_date_label(filters.get("start_date", ""))
    end_label = _format_date_label(filters.get("end_date", ""))
    if start_label and end_label and start_label != end_label:
        return f"{start_label} - {end_label}"
    return start_label or end_label or "Selected period"


def _event_is_parent_highlight(event_payload: dict) -> bool:
    text_value = " ".join(
        [
            str(event_payload.get("type_name", "") or ""),
            str(event_payload.get("title", "") or ""),
            str(event_payload.get("description", "") or ""),
        ]
    ).lower()
    return any(
        keyword in text_value
        for keyword in (
            "exam",
            "assessment",
            "quiz",
            "vacation",
            "holiday",
            "parent",
            "meeting",
            "deadline",
            "visit",
            "trip",
        )
    )


def _build_calendar_pdf_filename(branch_name: str, academic_year_name: str, filters: dict) -> str:
    base = f"academic_calendar_{branch_name}_{academic_year_name}_{filters.get('start_date', '')}_{filters.get('end_date', '')}"
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower()
    return f"{cleaned or 'academic_calendar_report'}.pdf"


def _build_academic_calendar_pdf_bytes(
    *,
    calendar_events: list[dict],
    branch_name: str,
    academic_year_name: str,
    filters: dict,
) -> bytes:
    period_label = _calendar_report_period_label(filters)
    subtitle = (
        f"{branch_name} | Academic Year {academic_year_name} | "
        f"{period_label} | Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    pdf = _CalendarPdfReport(
        "Parent Academic Calendar Report",
        subtitle,
        logos=CALENDAR_PDF_LOGOS,
    )
    pdf.paragraph(
        "This parent-facing calendar report summarizes school activities, events, assessments, meetings, "
        "vacations, deadlines, and visits for the selected calendar period."
    )

    total_events = len(calendar_events)
    upcoming_events = sum(1 for event in calendar_events if event.get("status") not in {"Completed", "Cancelled"})
    cancelled_events = sum(1 for event in calendar_events if event.get("status") == "Cancelled")
    highlight_events = [event for event in calendar_events if _event_is_parent_highlight(event)]
    all_school_events = sum(1 for event in calendar_events if event.get("target_group") == "All School")
    pdf.kpi_grid(
        [
            ("Total Events", str(total_events), "Selected period", "#0A4EA3"),
            ("Parent Highlights", str(len(highlight_events)), "Exams, meetings, trips", "#DB2777"),
            ("Upcoming / Active", str(upcoming_events), "Not completed/cancelled", "#C47A00"),
            ("All School", str(all_school_events), "Shared with everyone", "#0F766E"),
            ("Cancelled", str(cancelled_events), "Marked cancelled", "#9F2D1F"),
        ]
    )

    type_counts: dict[str, dict[str, Any]] = {}
    for event in calendar_events:
        type_name = str(event.get("type_name") or "Uncategorized")
        row = type_counts.setdefault(
            type_name,
            {
                "count": 0,
                "color": event.get("type_color", "#64748B"),
                "icon": event.get("type_icon", "info"),
            },
        )
        row["count"] += 1
    if type_counts:
        pdf.heading("Event Type Summary")
        x = pdf.margin
        row_y = pdf.y - 24
        max_x = pdf.width - pdf.margin
        for type_name, row in sorted(type_counts.items(), key=lambda item: (-item[1]["count"], item[0])):
            label = f"{_icon_label(row.get('icon', ''), type_name)} {type_name[:20]} ({row['count']})"
            pill_width = min(150, max(70, len(label) * 4.7))
            if x + pill_width > max_x:
                pdf.y = row_y - 12
                pdf.ensure_space(30)
                x = pdf.margin
                row_y = pdf.y - 24
            pdf.badge(x, row_y, label, row.get("color", "#64748B"), width=pill_width, height=18)
            x += pill_width + 7
        pdf.y = row_y - 20

    if highlight_events:
        pdf.heading("Important Parent Highlights")
        for event in highlight_events[:6]:
            pdf.event_card(event)

    grouped_events: dict[str, list[dict]] = defaultdict(list)
    for event in calendar_events:
        event_date = _date_from_iso(event.get("event_date", ""))
        month_key = event_date.strftime("%B %Y") if event_date else "Undated Events"
        grouped_events[month_key].append(event)

    pdf.heading("Events By Month")
    if not grouped_events:
        pdf.paragraph("No calendar events were found for the selected period.")
    else:
        for month_label, events in grouped_events.items():
            pdf.ensure_space(36)
            pdf.text(pdf.margin, pdf.y, month_label, size=11, color="#17365D", bold=True)
            pdf.y -= 13
            pdf.line(pdf.margin, pdf.y, pdf.width - pdf.margin, pdf.y, "#D8E5F4", width=0.6)
            pdf.y -= 10
            for event in events:
                pdf.event_card(event)

    return pdf.build()


def _build_filtered_event_query(
    db: Session,
    *,
    branch_id: int,
    academic_year_id: int,
    filters: dict,
):
    query = db.query(models.CalendarEvent).filter(
        models.CalendarEvent.branch_id == branch_id,
        models.CalendarEvent.academic_year_id == academic_year_id,
    )
    if filters["event_type_id"]:
        query = query.filter(models.CalendarEvent.event_type_id == filters["event_type_id"])
    if filters["status"]:
        query = query.filter(models.CalendarEvent.status == filters["status"])
    if filters["priority"]:
        query = query.filter(models.CalendarEvent.priority == filters["priority"])
    if filters["start_date"]:
        query = query.filter(
            or_(
                models.CalendarEvent.end_date == None,
                models.CalendarEvent.end_date == "",
                models.CalendarEvent.end_date >= filters["start_date"],
            )
        )
    if filters["end_date"]:
        query = query.filter(models.CalendarEvent.event_date <= filters["end_date"])
    if filters["grade"]:
        section_ids = [
            section_id
            for section_id, grade in filters["section_grade_lookup"].items()
            if grade == filters["grade"]
        ]
        if section_ids:
            query = query.filter(
                or_(
                    models.CalendarEvent.target_grade == filters["grade"],
                    models.CalendarEvent.target_grade == ALL_GRADES_VALUE,
                    models.CalendarEvent.target_group == "All School",
                    models.CalendarEvent.target_section_id.in_(section_ids),
                )
            )
        else:
            query = query.filter(
                or_(
                    models.CalendarEvent.target_grade.in_(
                        [filters["grade"], ALL_GRADES_VALUE]
                    ),
                    models.CalendarEvent.target_group == "All School",
                )
            )
    if filters["section_id"]:
        section_scope_filters = [
            models.CalendarEvent.target_section_id == filters["section_id"],
            models.CalendarEvent.target_grade == ALL_GRADES_VALUE,
            models.CalendarEvent.target_group == "All School",
        ]
        section_grade = filters["section_grade_lookup"].get(filters["section_id"])
        if section_grade:
            section_scope_filters.append(models.CalendarEvent.target_grade == section_grade)
        query = query.filter(or_(*section_scope_filters))
    if filters["teacher_id"]:
        assignment_event_ids = [
            row[0]
            for row in db.query(models.CalendarEventAssignment.calendar_event_id).filter(
                models.CalendarEventAssignment.teacher_id == filters["teacher_id"],
            ).all()
        ]
        query = query.filter(models.CalendarEvent.id.in_(assignment_event_ids or [-1]))
    if filters["user_id"]:
        assignment_event_ids = [
            row[0]
            for row in db.query(models.CalendarEventAssignment.calendar_event_id).filter(
                models.CalendarEventAssignment.user_id == filters["user_id"],
            ).all()
        ]
        query = query.filter(models.CalendarEvent.id.in_(assignment_event_ids or [-1]))
    return query


def _week_bounds_for(day_value: date) -> tuple[str, str]:
    start = day_value - timedelta(days=(day_value.weekday() + 1) % 7)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _filter_events_overlapping(query, start_iso: str, end_iso: str):
    return query.filter(
        models.CalendarEvent.event_date <= end_iso,
        or_(
            models.CalendarEvent.end_date == None,
            models.CalendarEvent.end_date == "",
            models.CalendarEvent.end_date >= start_iso,
        ),
    )


def _build_summary_cards(
    db: Session,
    *,
    branch_id: int,
    academic_year_id: int,
    current_user,
    today_value: date,
):
    month_start = today_value.replace(day=1)
    month_start_iso, month_end_iso = _month_bounds(month_start)
    week_start_iso, week_end_iso = _week_bounds_for(today_value)
    scoped_events = db.query(models.CalendarEvent).filter(
        models.CalendarEvent.branch_id == branch_id,
        models.CalendarEvent.academic_year_id == academic_year_id,
    )
    events_this_month = _filter_events_overlapping(
        scoped_events,
        month_start_iso,
        month_end_iso,
    ).count()
    upcoming = scoped_events.filter(
        or_(
            models.CalendarEvent.end_date == None,
            models.CalendarEvent.end_date == "",
            models.CalendarEvent.end_date >= today_value.isoformat(),
        ),
        models.CalendarEvent.status != "Cancelled",
    ).count()
    type_rows = _get_event_types(db, branch_id, academic_year_id, include_inactive=True)
    assessment_type_ids = [
        row.id
        for row in type_rows
        if any(
            keyword in str(row.name or "").strip().lower()
            for keyword in ("assessment", "quiz", "exam")
        )
    ]
    assessment_query = _filter_events_overlapping(
        scoped_events,
        week_start_iso,
        week_end_iso,
    )
    if assessment_type_ids:
        assessment_query = assessment_query.filter(
            models.CalendarEvent.event_type_id.in_(assessment_type_ids)
        )
    holidays_type_ids = [
        row.id
        for row in type_rows
        if any(
            keyword in str(row.name or "").strip().lower()
            for keyword in ("holiday", "vacation")
        )
    ]
    holiday_query = scoped_events
    if holidays_type_ids:
        holiday_query = holiday_query.filter(
            models.CalendarEvent.event_type_id.in_(holidays_type_ids)
        )
    pending = scoped_events.filter(
        models.CalendarEvent.end_date < today_value.isoformat(),
        models.CalendarEvent.status.in_(["Planned", "Confirmed", "In Progress"]),
    ).count()

    user_id = getattr(current_user, "id", None)
    teacher_user_id = str(getattr(current_user, "user_id", "") or "").strip()
    teacher_ids = [
        row[0]
        for row in db.query(models.Teacher.id).filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
            models.Teacher.teacher_id == teacher_user_id,
        ).all()
    ]
    assigned_event_ids = []
    assignment_query = db.query(models.CalendarEventAssignment.calendar_event_id)
    assignment_filters = []
    if user_id:
        assignment_filters.append(models.CalendarEventAssignment.user_id == user_id)
    if teacher_ids:
        assignment_filters.append(models.CalendarEventAssignment.teacher_id.in_(teacher_ids))
    if assignment_filters:
        assigned_event_ids = [
            row[0]
            for row in assignment_query.filter(or_(*assignment_filters)).all()
        ]
    assigned_to_me = 0
    if assigned_event_ids:
        assigned_to_me = scoped_events.filter(
            models.CalendarEvent.id.in_(assigned_event_ids),
            models.CalendarEvent.status != "Cancelled",
        ).count()

    return [
        {
            "label": "Events This Month",
            "value": events_this_month,
            "icon": "calendar",
            "note": month_start.strftime("%B %Y"),
        },
        {
            "label": "Upcoming",
            "value": upcoming,
            "icon": "open",
            "note": "Not cancelled",
        },
        {
            "label": "Assessments This Week",
            "value": assessment_query.count(),
            "icon": "clipboard-check",
            "note": f"{week_start_iso} to {week_end_iso}",
        },
        {
            "label": "Holidays / Vacations",
            "value": holiday_query.count(),
            "icon": "home",
            "note": "Configured calendar type",
        },
        {
            "label": "Overdue / Pending",
            "value": pending,
            "icon": "deadline",
            "note": "Past planned work",
        },
        {
            "label": "Assigned To Me",
            "value": assigned_to_me,
            "icon": "user-plus",
            "note": "Direct user or linked teacher",
        },
    ]


def _build_event_payloads(
    db: Session,
    events,
    *,
    event_types,
    teachers,
    users,
    sections,
):
    event_ids = [event.id for event in events]
    type_lookup = {event_type.id: event_type for event_type in event_types}
    teacher_lookup = {teacher.id: teacher for teacher in teachers}
    user_lookup = {user.id: user for user in users}
    section_lookup = {section.id: section for section in sections}
    assignment_map = _build_assignment_map(db, event_ids, teacher_lookup, user_lookup)
    return _sort_event_payloads(
        [
            _serialize_event(
                event,
                type_lookup=type_lookup,
                section_lookup=section_lookup,
                teacher_lookup=teacher_lookup,
                assignment_payload=assignment_map.get(event.id, {}),
            )
            for event in events
        ]
    )


def _current_return_path(request: Request) -> str:
    path = request.url.path
    query = str(request.url.query or "")
    return f"{path}?{query}" if query else path


def _build_filter_payload(
    *,
    month: str,
    view: str,
    event_type_id: str,
    status: str,
    priority: str,
    grade: str,
    section_id: str,
    teacher_id: str,
    user_id: str,
    start_date: str,
    end_date: str,
    sections,
) -> dict:
    selected_month = _normalize_month(month)
    default_start, default_end = _month_bounds(selected_month)
    normalized_start = _normalize_date(start_date) or default_start
    normalized_end = _normalize_date(end_date) or default_end
    if normalized_start > normalized_end:
        normalized_start, normalized_end = normalized_end, normalized_start
    selected_grade = _normalize_spaces(grade).upper()
    if selected_grade in {"K", "KINDERGARTEN"}:
        selected_grade = "KG"
    if selected_grade not in GRADE_OPTIONS:
        selected_grade = ""
    section_grade_lookup = {
        section.id: str(section.grade_level or "").strip().upper()
        for section in sections
    }
    return {
        "view": view if view in {"month", "agenda"} else "month",
        "selected_month": selected_month,
        "month": selected_month.strftime("%Y-%m"),
        "event_type_id": _parse_int(event_type_id),
        "status": status if status in EVENT_STATUS_OPTIONS else "",
        "priority": priority if priority in PRIORITY_OPTIONS else "",
        "grade": selected_grade,
        "section_id": _parse_int(section_id),
        "teacher_id": _parse_int(teacher_id),
        "user_id": _parse_int(user_id),
        "start_date": normalized_start,
        "end_date": normalized_end,
        "section_grade_lookup": section_grade_lookup,
    }


def _normalize_id_list(values) -> list[int]:
    parsed_ids = []
    for value in values or []:
        parsed_value = _parse_int(value)
        if parsed_value is None:
            continue
        parsed_ids.append(parsed_value)
    return sorted(set(parsed_ids))


def _validate_event_type_id(db: Session, event_type_id, branch_id: int, academic_year_id: int):
    if not event_type_id:
        return None
    return db.query(models.CalendarEventType).filter(
        models.CalendarEventType.id == event_type_id,
        models.CalendarEventType.branch_id == branch_id,
        models.CalendarEventType.academic_year_id == academic_year_id,
    ).first()


def _normalize_event_form_payload(
    *,
    db: Session,
    branch_id: int,
    academic_year_id: int,
    title: str,
    event_type_id: str,
    event_date: str,
    end_date: str,
    start_time: str,
    end_time: str,
    all_day: str,
    description: str,
    target_group: str,
    target_grade: str,
    target_section_id: str,
    target_teacher_id: str,
    target_role: str,
    priority: str,
    status: str,
    recurrence_rule: str,
    recurrence_interval: str,
    recurrence_until: str,
    assigned_teacher_ids,
    assigned_user_ids,
):
    errors = []
    normalized_title = _normalize_spaces(title)
    if not normalized_title:
        errors.append("Event title is required.")
    elif len(normalized_title) > 180:
        errors.append("Event title must stay under 180 characters.")

    parsed_event_type_id = _parse_int(event_type_id)
    if parsed_event_type_id:
        event_type = _validate_event_type_id(
            db,
            parsed_event_type_id,
            branch_id,
            academic_year_id,
        )
        if not event_type:
            errors.append("Selected event type is not available in the active scope.")
            parsed_event_type_id = None
    normalized_date = _normalize_date(event_date)
    if not normalized_date:
        errors.append("Start date is required.")
    raw_end_date = str(end_date or "").strip()
    normalized_end_date = _normalize_date(raw_end_date)
    if raw_end_date and not normalized_end_date:
        errors.append("End date must use YYYY-MM-DD format.")
    if not normalized_end_date:
        normalized_end_date = normalized_date
    if normalized_date and normalized_end_date and normalized_end_date < normalized_date:
        errors.append("End date must be on or after the start date.")
    is_all_day = _is_checked(all_day)
    normalized_start = _normalize_time(start_time)
    normalized_end = _normalize_time(end_time)
    if str(start_time or "").strip() and not normalized_start:
        errors.append("Start time must use HH:MM format.")
    if str(end_time or "").strip() and not normalized_end:
        errors.append("End time must use HH:MM format.")
    if normalized_start and normalized_end and normalized_end < normalized_start:
        errors.append("End time must be after start time.")
    if is_all_day:
        normalized_start = ""
        normalized_end = ""

    normalized_target_group = _normalize_choice(
        target_group,
        TARGET_GROUP_OPTIONS,
        "All School",
    )
    raw_target_grade = _normalize_spaces(target_grade)
    normalized_grade = raw_target_grade.upper()
    if normalized_grade in {"K", "KINDERGARTEN"}:
        normalized_grade = "KG"
    elif normalized_grade in ALL_GRADES_ALIASES:
        normalized_grade = ALL_GRADES_VALUE
    if (
        normalized_grade
        and normalized_grade != ALL_GRADES_VALUE
        and normalized_grade not in GRADE_OPTIONS
    ):
        errors.append("Target grade must be KG or a grade from 1 to 12.")
        normalized_grade = ""
    normalized_section_token = _normalize_spaces(target_section_id)
    target_section_is_all = normalized_section_token.upper() in ALL_SECTIONS_ALIASES
    parsed_section_id = None if target_section_is_all else _parse_int(target_section_id)
    parsed_teacher_id = _parse_int(target_teacher_id)
    if parsed_section_id:
        section_row = db.query(models.PlanningSection).filter(
            models.PlanningSection.id == parsed_section_id,
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
        ).first()
        if not section_row:
            errors.append("Selected section is not available in the active scope.")
            parsed_section_id = None
        else:
            normalized_grade = str(section_row.grade_level or normalized_grade or "").strip().upper()
    if parsed_teacher_id:
        teacher_exists = db.query(models.Teacher.id).filter(
            models.Teacher.id == parsed_teacher_id,
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
        ).first()
        if not teacher_exists:
            errors.append("Selected target teacher is not available in the active scope.")
            parsed_teacher_id = None
    normalized_priority = _normalize_choice(priority, PRIORITY_OPTIONS, "Normal")
    normalized_status = _normalize_choice(status, EVENT_STATUS_OPTIONS, "Planned")
    normalized_recurrence = _normalize_choice(recurrence_rule, RECURRENCE_OPTIONS, "None")
    parsed_interval = _parse_int(recurrence_interval) or 1
    if parsed_interval < 1:
        parsed_interval = 1
    normalized_recurrence_until = _normalize_date(recurrence_until)
    if recurrence_until and not normalized_recurrence_until:
        errors.append("Recurrence end date must use YYYY-MM-DD format.")

    teacher_ids = _normalize_id_list(assigned_teacher_ids)
    user_ids = _normalize_id_list(assigned_user_ids)
    if teacher_ids:
        valid_teacher_ids = {
            row[0]
            for row in db.query(models.Teacher.id).filter(
                models.Teacher.branch_id == branch_id,
                models.Teacher.academic_year_id == academic_year_id,
                models.Teacher.id.in_(teacher_ids),
            ).all()
        }
        teacher_ids = sorted(valid_teacher_ids)
    if user_ids:
        valid_user_ids = {
            row[0]
            for row in db.query(models.User.id).filter(
                models.User.is_active == True,
                models.User.branch_id == branch_id,
                models.User.id.in_(user_ids),
            ).all()
        }
        user_ids = sorted(valid_user_ids)

    if normalized_target_group == "All School":
        normalized_grade = ALL_GRADES_VALUE
        parsed_section_id = None
        parsed_teacher_id = None
        target_role = ""
    elif parsed_section_id:
        normalized_target_group = "Section"
    elif target_section_is_all:
        normalized_target_group = "All School"
        normalized_grade = ALL_GRADES_VALUE
    elif normalized_grade:
        normalized_target_group = "Grade"
    elif parsed_teacher_id:
        normalized_target_group = "Teacher"
    elif _normalize_spaces(target_role) and normalized_target_group == "All School":
        normalized_target_group = "Custom"

    if normalized_target_group == "All School":
        normalized_grade = ALL_GRADES_VALUE
    elif normalized_target_group != "Grade":
        normalized_grade = ""
    if normalized_target_group != "Section":
        parsed_section_id = None
    if normalized_target_group != "Teacher":
        parsed_teacher_id = None
    elif parsed_teacher_id:
        teacher_ids = sorted(set(teacher_ids + [parsed_teacher_id]))
    if normalized_target_group not in {"Role", "Custom"}:
        target_role = ""

    return {
        "errors": errors,
        "payload": {
            "title": normalized_title,
            "event_type_id": parsed_event_type_id,
            "event_date": normalized_date,
            "end_date": normalized_end_date,
            "start_time": normalized_start or None,
            "end_time": normalized_end or None,
            "all_day": is_all_day,
            "description": str(description or "").strip(),
            "target_group": normalized_target_group,
            "target_grade": normalized_grade or None,
            "target_section_id": parsed_section_id,
            "target_teacher_id": parsed_teacher_id,
            "target_role": _normalize_spaces(target_role) or None,
            "priority": normalized_priority,
            "status": normalized_status,
            "recurrence_rule": normalized_recurrence,
            "recurrence_interval": parsed_interval,
            "recurrence_until": normalized_recurrence_until or None,
            "assigned_teacher_ids": teacher_ids,
            "assigned_user_ids": user_ids,
        },
    }


def _sync_event_assignments(
    db: Session,
    event,
    *,
    teacher_ids: list[int],
    user_ids: list[int],
    assignment_role: str = "",
):
    existing_rows = db.query(models.CalendarEventAssignment).filter(
        models.CalendarEventAssignment.calendar_event_id == event.id
    ).all()
    for row in existing_rows:
        db.delete(row)
    db.flush()

    created_rows = []
    for teacher_id in teacher_ids:
        row = models.CalendarEventAssignment(
            calendar_event_id=event.id,
            teacher_id=teacher_id,
            assignment_role=assignment_role,
        )
        db.add(row)
        created_rows.append(row)
    for user_id in user_ids:
        row = models.CalendarEventAssignment(
            calendar_event_id=event.id,
            user_id=user_id,
            assignment_role=assignment_role,
        )
        db.add(row)
        created_rows.append(row)
    db.flush()
    return created_rows


def _resolve_notification_recipients(
    db: Session,
    *,
    branch_id: int,
    teacher_ids: list[int],
    user_ids: list[int],
):
    recipient_rows = []
    if user_ids:
        recipient_rows.extend(
            db.query(models.User).filter(
                models.User.id.in_(user_ids),
                models.User.is_active == True,
                models.User.branch_id == branch_id,
            ).all()
        )
    if teacher_ids:
        teacher_rows = db.query(models.Teacher).filter(
            models.Teacher.id.in_(teacher_ids),
            models.Teacher.branch_id == branch_id,
        ).all()
        teacher_user_ids = {
            str(getattr(teacher, "teacher_id", "") or "").strip()
            for teacher in teacher_rows
            if str(getattr(teacher, "teacher_id", "") or "").strip()
        }
        if teacher_user_ids:
            recipient_rows.extend(
                db.query(models.User).filter(
                    models.User.is_active == True,
                    models.User.branch_id == branch_id,
                    or_(
                        models.User.user_id.in_(teacher_user_ids),
                        models.User.username.in_(teacher_user_ids),
                    ),
                ).all()
            )
    recipients = {}
    for user in recipient_rows:
        user_key = str(getattr(user, "user_id", "") or "").strip()
        if user_key:
            recipients[user_key] = user
    return list(recipients.values())


def _create_calendar_notifications(
    db: Session,
    *,
    event,
    event_type_name: str,
    recipients,
    current_user,
    kind: str,
):
    if not recipients:
        return
    time_label = _build_time_label(event)
    event_end_date = _event_end_date_value(event)
    date_range_label = _build_date_range_label(event.event_date, event_end_date)
    detail_link = f"/academic-calendar/?event_id={event.id}&start_date={event.event_date}&end_date={event_end_date}"
    safe_link = html.escape(detail_link, quote=True)
    details = {
        "calendar_event_id": event.id,
        "event_date": event.event_date,
        "end_date": event_end_date,
        "event_type": event_type_name,
        "time": time_label,
        "link": detail_link,
    }
    for recipient in recipients:
        notification = models.SystemNotification(
            recipient_user_id=recipient.user_id,
            requesting_user_id=getattr(current_user, "user_id", None),
            request_type="Academic Calendar",
            title=f"Calendar Event {kind}: {event.title}"[:160],
            message=(
                f"{html.escape(event_type_name)} is scheduled for {html.escape(date_range_label)} "
                f"({html.escape(time_label)}). Priority: {html.escape(event.priority)}. "
                f"Status: {html.escape(event.status)}. "
                f"<a href=\"{safe_link}\">Open calendar event</a>."
            ),
            details=json.dumps(details),
            status="New",
            recipient_scope="User",
        )
        db.add(notification)
        db.flush()
        db.add(
            models.CalendarEventNotification(
                calendar_event_id=event.id,
                system_notification_id=notification.id,
                notification_kind=kind,
            )
        )


def _get_event_for_scope(
    db: Session,
    *,
    event_id: int,
    branch_id: int,
    academic_year_id: int,
):
    return db.query(models.CalendarEvent).filter(
        models.CalendarEvent.id == event_id,
        models.CalendarEvent.branch_id == branch_id,
        models.CalendarEvent.academic_year_id == academic_year_id,
    ).first()


@router.get("/academic-calendar")
def academic_calendar_redirect():
    return RedirectResponse(url="/academic-calendar/", status_code=302)


@router.get("/academic-calendar/")
def academic_calendar_home(
    request: Request,
    view: str = Query("month"),
    month: str = Query(""),
    event_type_id: str = Query(""),
    status: str = Query(""),
    priority: str = Query(""),
    grade: str = Query(""),
    section_id: str = Query(""),
    teacher_id: str = Query(""),
    user_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    event_id: str = Query(""),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return redirect_response
    branch_id, academic_year_id = _get_scope_ids(current_user)
    if not branch_id or not academic_year_id:
        return RedirectResponse(url="/dashboard?error=missing-scope", status_code=302)

    _ensure_calendar_event_schema(db)
    _ensure_default_event_types(db, branch_id, academic_year_id)
    teachers, users, sections = _get_scope_options(db, branch_id, academic_year_id)
    event_types = _get_event_types(
        db,
        branch_id,
        academic_year_id,
        include_inactive=True,
    )
    active_event_types = [event_type for event_type in event_types if event_type.is_active]
    filters = _build_filter_payload(
        month=month,
        view=view,
        event_type_id=event_type_id,
        status=status,
        priority=priority,
        grade=grade,
        section_id=section_id,
        teacher_id=teacher_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        sections=sections,
    )
    query = _build_filtered_event_query(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        filters=filters,
    )
    event_rows = query.order_by(
        models.CalendarEvent.event_date.asc(),
        models.CalendarEvent.start_time.asc(),
        models.CalendarEvent.title.asc(),
    ).all()
    calendar_events = _build_event_payloads(
        db,
        event_rows,
        event_types=event_types,
        teachers=teachers,
        users=users,
        sections=sections,
    )
    selected_month = filters["selected_month"]
    month_weeks = _build_month_grid(selected_month, calendar_events)
    event_type_payloads = [_build_type_payload(event_type) for event_type in event_types]
    active_event_type_payloads = [
        _build_type_payload(event_type) for event_type in active_event_types
    ]
    section_payloads = [
        {
            "id": section.id,
            "label": _build_section_label(section),
            "grade_level": str(section.grade_level or "").strip().upper(),
        }
        for section in sections
    ]
    teacher_payloads = [
        {
            "id": teacher.id,
            "teacher_id": teacher.teacher_id or "",
            "label": _build_teacher_display_name(teacher),
        }
        for teacher in teachers
    ]
    user_payloads = [
        {
            "id": user.id,
            "user_id": user.user_id or "",
            "label": _build_user_display_name(user),
        }
        for user in users
    ]

    return templates.TemplateResponse(
        request,
        "academic_calendar.html",
        {
            "request": request,
            "user": current_user,
            "calendar_events": calendar_events,
            "calendar_events_json": json.dumps(calendar_events),
            "event_types": event_type_payloads,
            "active_event_types": active_event_type_payloads,
            "sections": section_payloads,
            "teachers": teacher_payloads,
            "users": user_payloads,
            "grade_options": GRADE_OPTIONS,
            "target_grade_options": TARGET_GRADE_OPTIONS,
            "all_sections_label": ALL_SECTIONS_LABEL,
            "all_sections_value": ALL_SECTIONS_VALUE,
            "status_options": EVENT_STATUS_OPTIONS,
            "priority_options": PRIORITY_OPTIONS,
            "target_group_options": TARGET_GROUP_OPTIONS,
            "recurrence_options": RECURRENCE_OPTIONS,
            "filters": filters,
            "month_weeks": month_weeks,
            "week_day_names": ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"),
            "calendar_view": filters["view"],
            "selected_month_label": selected_month.strftime("%B %Y"),
            "previous_month": _month_link_value(selected_month, -1),
            "next_month": _month_link_value(selected_month, 1),
            "pdf_export_url": _build_calendar_export_url(filters, filters["view"]),
            "summary_cards": _build_summary_cards(
                db,
                branch_id=branch_id,
                academic_year_id=academic_year_id,
                current_user=current_user,
                today_value=date.today(),
            ),
            "can_manage_calendar": _can_manage_calendar(current_user),
            "selected_event_id": _parse_int(event_id),
            "return_to": _current_return_path(request),
            "notice": str(request.query_params.get("notice", "") or "").strip(),
            "error_message": str(request.query_params.get("error", "") or "").strip(),
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="academic-calendar",
            ),
        },
    )


@router.get("/academic-calendar/export.pdf")
def export_academic_calendar_pdf(
    request: Request,
    view: str = Query("month"),
    month: str = Query(""),
    event_type_id: str = Query(""),
    status: str = Query(""),
    priority: str = Query(""),
    grade: str = Query(""),
    section_id: str = Query(""),
    teacher_id: str = Query(""),
    user_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return redirect_response
    branch_id, academic_year_id = _get_scope_ids(current_user)
    if not branch_id or not academic_year_id:
        return RedirectResponse(url="/dashboard?error=missing-scope", status_code=302)

    _ensure_calendar_event_schema(db)
    _ensure_default_event_types(db, branch_id, academic_year_id)
    teachers, users, sections = _get_scope_options(db, branch_id, academic_year_id)
    event_types = _get_event_types(
        db,
        branch_id,
        academic_year_id,
        include_inactive=True,
    )
    filters = _build_filter_payload(
        month=month,
        view=view,
        event_type_id=event_type_id,
        status=status,
        priority=priority,
        grade=grade,
        section_id=section_id,
        teacher_id=teacher_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        sections=sections,
    )
    query = _build_filtered_event_query(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        filters=filters,
    )
    event_rows = query.order_by(
        models.CalendarEvent.event_date.asc(),
        models.CalendarEvent.start_time.asc(),
        models.CalendarEvent.title.asc(),
    ).all()
    calendar_events = _build_event_payloads(
        db,
        event_rows,
        event_types=event_types,
        teachers=teachers,
        users=users,
        sections=sections,
    )
    branch_row = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    academic_year_row = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()
    branch_name = getattr(branch_row, "name", None) or "School"
    academic_year_name = getattr(academic_year_row, "year_name", None) or "Academic Year"
    pdf_bytes = _build_academic_calendar_pdf_bytes(
        calendar_events=calendar_events,
        branch_name=branch_name,
        academic_year_name=academic_year_name,
        filters=filters,
    )
    filename = _build_calendar_pdf_filename(branch_name, academic_year_name, filters)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/academic-calendar/events")
def create_calendar_event(
    request: Request,
    title: str = Form(""),
    event_type_id: str = Form(""),
    event_date: str = Form(""),
    end_date: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    all_day: str = Form(""),
    description: str = Form(""),
    target_group: str = Form("All School"),
    target_grade: str = Form(""),
    target_section_id: str = Form(""),
    target_teacher_id: str = Form(""),
    target_role: str = Form(""),
    priority: str = Form("Normal"),
    status: str = Form("Planned"),
    recurrence_rule: str = Form("None"),
    recurrence_interval: str = Form("1"),
    recurrence_until: str = Form(""),
    assigned_teacher_ids: list[str] = Form([]),
    assigned_user_ids: list[str] = Form([]),
    return_to: str = Form("/academic-calendar/"),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return redirect_response
    if not _can_manage_calendar(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)
    safe_return_to = _safe_redirect_path(return_to)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    _ensure_calendar_event_schema(db)
    normalized = _normalize_event_form_payload(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        title=title,
        event_type_id=event_type_id,
        event_date=event_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        description=description,
        target_group=target_group,
        target_grade=target_grade,
        target_section_id=target_section_id,
        target_teacher_id=target_teacher_id,
        target_role=target_role,
        priority=priority,
        status=status,
        recurrence_rule=recurrence_rule,
        recurrence_interval=recurrence_interval,
        recurrence_until=recurrence_until,
        assigned_teacher_ids=assigned_teacher_ids,
        assigned_user_ids=assigned_user_ids,
    )
    if normalized["errors"]:
        return _redirect_with_query(safe_return_to, "error", " ".join(normalized["errors"]))

    payload = normalized["payload"]
    teacher_ids = payload.pop("assigned_teacher_ids")
    user_ids = payload.pop("assigned_user_ids")
    event = models.CalendarEvent(
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        created_by_user_id=getattr(current_user, "user_id", None),
        updated_by_user_id=getattr(current_user, "user_id", None),
        **payload,
    )
    db.add(event)
    db.flush()
    _sync_event_assignments(
        db,
        event,
        teacher_ids=teacher_ids,
        user_ids=user_ids,
        assignment_role=payload.get("target_role") or "",
    )
    event_type = _validate_event_type_id(db, event.event_type_id, branch_id, academic_year_id)
    recipients = _resolve_notification_recipients(
        db,
        branch_id=branch_id,
        teacher_ids=teacher_ids,
        user_ids=user_ids,
    )
    _create_calendar_notifications(
        db,
        event=event,
        event_type_name=getattr(event_type, "name", None) or "Calendar Event",
        recipients=recipients,
        current_user=current_user,
        kind="Assigned",
    )
    db.commit()
    return _redirect_with_query(safe_return_to, "notice", "Calendar event created.")


@router.post("/academic-calendar/events/{event_id}")
def update_calendar_event(
    event_id: int,
    request: Request,
    title: str = Form(""),
    event_type_id: str = Form(""),
    event_date: str = Form(""),
    end_date: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    all_day: str = Form(""),
    description: str = Form(""),
    target_group: str = Form("All School"),
    target_grade: str = Form(""),
    target_section_id: str = Form(""),
    target_teacher_id: str = Form(""),
    target_role: str = Form(""),
    priority: str = Form("Normal"),
    status: str = Form("Planned"),
    recurrence_rule: str = Form("None"),
    recurrence_interval: str = Form("1"),
    recurrence_until: str = Form(""),
    assigned_teacher_ids: list[str] = Form([]),
    assigned_user_ids: list[str] = Form([]),
    return_to: str = Form("/academic-calendar/"),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return redirect_response
    if not _can_manage_calendar(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)
    safe_return_to = _safe_redirect_path(return_to)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    _ensure_calendar_event_schema(db)
    event = _get_event_for_scope(
        db,
        event_id=event_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    if not event:
        return _redirect_with_query(safe_return_to, "error", "Calendar event was not found.")

    normalized = _normalize_event_form_payload(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        title=title,
        event_type_id=event_type_id,
        event_date=event_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        description=description,
        target_group=target_group,
        target_grade=target_grade,
        target_section_id=target_section_id,
        target_teacher_id=target_teacher_id,
        target_role=target_role,
        priority=priority,
        status=status,
        recurrence_rule=recurrence_rule,
        recurrence_interval=recurrence_interval,
        recurrence_until=recurrence_until,
        assigned_teacher_ids=assigned_teacher_ids,
        assigned_user_ids=assigned_user_ids,
    )
    if normalized["errors"]:
        return _redirect_with_query(safe_return_to, "error", " ".join(normalized["errors"]))
    payload = normalized["payload"]
    teacher_ids = payload.pop("assigned_teacher_ids")
    user_ids = payload.pop("assigned_user_ids")
    for key, value in payload.items():
        setattr(event, key, value)
    event.updated_by_user_id = getattr(current_user, "user_id", None)
    event.updated_at = datetime.utcnow()
    _sync_event_assignments(
        db,
        event,
        teacher_ids=teacher_ids,
        user_ids=user_ids,
        assignment_role=payload.get("target_role") or "",
    )
    event_type = _validate_event_type_id(db, event.event_type_id, branch_id, academic_year_id)
    recipients = _resolve_notification_recipients(
        db,
        branch_id=branch_id,
        teacher_ids=teacher_ids,
        user_ids=user_ids,
    )
    _create_calendar_notifications(
        db,
        event=event,
        event_type_name=getattr(event_type, "name", None) or "Calendar Event",
        recipients=recipients,
        current_user=current_user,
        kind="Updated" if event.status != "Cancelled" else "Cancelled",
    )
    db.commit()
    return _redirect_with_query(safe_return_to, "notice", "Calendar event updated.")


@router.post("/academic-calendar/events/{event_id}/status")
def update_calendar_event_status(
    event_id: int,
    request: Request,
    status: str = Form(""),
    return_to: str = Form("/academic-calendar/"),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return redirect_response
    if not _can_manage_calendar(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)
    safe_return_to = _safe_redirect_path(return_to)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    _ensure_calendar_event_schema(db)
    event = _get_event_for_scope(
        db,
        event_id=event_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    if not event:
        return _redirect_with_query(safe_return_to, "error", "Calendar event was not found.")
    normalized_status = _normalize_choice(status, EVENT_STATUS_OPTIONS, "")
    if not normalized_status:
        return _redirect_with_query(safe_return_to, "error", "Status change is not available.")
    if event.status != normalized_status:
        event.status = normalized_status
        event.updated_by_user_id = getattr(current_user, "user_id", None)
        event.updated_at = datetime.utcnow()
        assignment_rows = db.query(models.CalendarEventAssignment).filter(
            models.CalendarEventAssignment.calendar_event_id == event.id
        ).all()
        recipients = _resolve_notification_recipients(
            db,
            branch_id=branch_id,
            teacher_ids=[row.teacher_id for row in assignment_rows if row.teacher_id],
            user_ids=[row.user_id for row in assignment_rows if row.user_id],
        )
        event_type = _validate_event_type_id(db, event.event_type_id, branch_id, academic_year_id)
        _create_calendar_notifications(
            db,
            event=event,
            event_type_name=getattr(event_type, "name", None) or "Calendar Event",
            recipients=recipients,
            current_user=current_user,
            kind="Status Updated",
        )
        db.commit()
    return _redirect_with_query(safe_return_to, "notice", "Calendar event status updated.")


@router.post("/academic-calendar/events/{event_id}/delete")
def delete_calendar_event(
    event_id: int,
    request: Request,
    return_to: str = Form("/academic-calendar/"),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_current_user_or_redirect(request, db)
    if redirect_response:
        return redirect_response
    if not _can_manage_calendar(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)
    safe_return_to = _safe_redirect_path(return_to)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    _ensure_calendar_event_schema(db)
    event = _get_event_for_scope(
        db,
        event_id=event_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    if not event:
        return _redirect_with_query(safe_return_to, "error", "Calendar event was not found.")
    db.query(models.CalendarEventNotification).filter(
        models.CalendarEventNotification.calendar_event_id == event.id
    ).delete(synchronize_session=False)
    db.query(models.CalendarEventAssignment).filter(
        models.CalendarEventAssignment.calendar_event_id == event.id
    ).delete(synchronize_session=False)
    db.delete(event)
    db.commit()
    return _redirect_with_query(safe_return_to, "notice", "Calendar event deleted.")


def _build_calendar_config_context(
    request: Request,
    db: Session,
    current_user,
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    _ensure_calendar_event_schema(db)
    _ensure_default_event_types(db, branch_id, academic_year_id)
    event_types = _get_event_types(
        db,
        branch_id,
        academic_year_id,
        include_inactive=True,
    )
    rows = []
    for event_type in event_types:
        usage_count = db.query(models.CalendarEvent).filter(
            models.CalendarEvent.branch_id == branch_id,
            models.CalendarEvent.academic_year_id == academic_year_id,
            models.CalendarEvent.event_type_id == event_type.id,
        ).count()
        payload = _build_type_payload(event_type)
        rows.append(
            {
                **payload,
                "usage_count": usage_count,
                "can_delete": usage_count == 0,
            }
        )
    return {
        "calendar_event_types": rows,
        "icon_options": ICON_OPTIONS,
        "configuration_modules": _get_configuration_modules("academic-calendar"),
        "notice": str(request.query_params.get("notice", "") or "").strip(),
        "error_message": str(request.query_params.get("error", "") or "").strip(),
    }


@router.get("/system-configuration/calendar")
def system_configuration_calendar(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_configuration_access(request, db)
    if redirect_response:
        return redirect_response
    return templates.TemplateResponse(
        request,
        "system_configuration_calendar.html",
        {
            "request": request,
            "user": current_user,
            **_build_calendar_config_context(request, db, current_user),
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="system-configuration",
                title="Academic Calendar Configuration",
                intro="Configure event types, colors, and icons for the active branch and academic year.",
            ),
        },
    )


@router.post("/system-configuration/calendar/event-types")
def create_calendar_event_type(
    request: Request,
    name: str = Form(""),
    color: str = Form("#0A4EA3"),
    icon: str = Form("calendar"),
    sort_order: str = Form("0"),
    return_to: str = Form("/system-configuration/calendar"),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_configuration_access(request, db)
    if redirect_response:
        return redirect_response
    safe_return_to = _safe_redirect_path(return_to, "/system-configuration/calendar")
    branch_id, academic_year_id = _get_scope_ids(current_user)
    normalized_name = _normalize_spaces(name)
    if not normalized_name:
        return _redirect_with_query(safe_return_to, "error", "Event type name is required.")
    event_type = models.CalendarEventType(
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        name=normalized_name,
        color=_normalize_event_color(color),
        icon=_normalize_icon_name(icon),
        is_active=True,
        sort_order=_parse_int(sort_order) or 0,
    )
    db.add(event_type)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_with_query(
            safe_return_to,
            "error",
            "An event type with this name already exists for the active scope.",
        )
    return _redirect_with_query(safe_return_to, "notice", "Calendar event type added.")


@router.post("/system-configuration/calendar/event-types/{event_type_id}")
def update_calendar_event_type(
    event_type_id: int,
    request: Request,
    name: str = Form(""),
    color: str = Form("#0A4EA3"),
    icon: str = Form("calendar"),
    sort_order: str = Form("0"),
    is_active: str = Form(""),
    return_to: str = Form("/system-configuration/calendar"),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_configuration_access(request, db)
    if redirect_response:
        return redirect_response
    safe_return_to = _safe_redirect_path(return_to, "/system-configuration/calendar")
    branch_id, academic_year_id = _get_scope_ids(current_user)
    event_type = db.query(models.CalendarEventType).filter(
        models.CalendarEventType.id == event_type_id,
        models.CalendarEventType.branch_id == branch_id,
        models.CalendarEventType.academic_year_id == academic_year_id,
    ).first()
    if not event_type:
        return _redirect_with_query(safe_return_to, "error", "Event type was not found.")
    normalized_name = _normalize_spaces(name)
    if not normalized_name:
        return _redirect_with_query(safe_return_to, "error", "Event type name is required.")
    event_type.name = normalized_name
    event_type.color = _normalize_event_color(color)
    event_type.icon = _normalize_icon_name(icon)
    event_type.sort_order = _parse_int(sort_order) or 0
    event_type.is_active = _is_checked(is_active)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_with_query(
            safe_return_to,
            "error",
            "Another event type already uses this name.",
        )
    return _redirect_with_query(safe_return_to, "notice", "Calendar event type updated.")


@router.post("/system-configuration/calendar/event-types/{event_type_id}/delete")
def delete_calendar_event_type(
    event_type_id: int,
    request: Request,
    return_to: str = Form("/system-configuration/calendar"),
    db: Session = Depends(get_db),
):
    current_user, redirect_response = _get_configuration_access(request, db)
    if redirect_response:
        return redirect_response
    safe_return_to = _safe_redirect_path(return_to, "/system-configuration/calendar")
    branch_id, academic_year_id = _get_scope_ids(current_user)
    event_type = db.query(models.CalendarEventType).filter(
        models.CalendarEventType.id == event_type_id,
        models.CalendarEventType.branch_id == branch_id,
        models.CalendarEventType.academic_year_id == academic_year_id,
    ).first()
    if not event_type:
        return _redirect_with_query(safe_return_to, "error", "Event type was not found.")
    usage_count = db.query(models.CalendarEvent).filter(
        models.CalendarEvent.event_type_id == event_type.id,
        models.CalendarEvent.branch_id == branch_id,
        models.CalendarEvent.academic_year_id == academic_year_id,
    ).count()
    if usage_count:
        event_type.is_active = False
        db.commit()
        return _redirect_with_query(
            safe_return_to,
            "notice",
            "Event type is used by events, so it was deactivated instead of deleted.",
        )
    db.delete(event_type)
    db.commit()
    return _redirect_with_query(safe_return_to, "notice", "Calendar event type deleted.")
