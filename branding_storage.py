from __future__ import annotations

import io
import os
import re
import shutil
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from starlette.responses import Response


BASE_DIR = Path(__file__).resolve().parent
STATIC_ROOT = BASE_DIR / "static"
BRANDING_ROOT = STATIC_ROOT / "branding"
TIS_LOGO_ROOT = BRANDING_ROOT / "tis" / "logos"
ORGANIZATIONS_ROOT = BRANDING_ROOT / "organizations"

LOGO_MAX_BYTES = 4 * 1024 * 1024
MAX_LOGO_PIXELS = 25_000_000
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".webp", ".svg"}

_DASH = "\u2013"
_AMP = "\u0026"
TIS_LOGO_FILENAMES = {
    "full_color_horizontal": f"TIS Logo {_DASH} Full Color {_DASH} Horizontal Layout.png",
    "full_color_stacked": f"TIS Logo {_DASH} Full Color {_DASH} Stacked Layout.png",
    "light_horizontal": f"TIS Logo {_DASH} White {_AMP} Light Orange {_DASH} Horizontal Layout.png",
    "light_stacked": f"TIS Logo {_DASH} White {_AMP} Light Orange {_DASH} Stacked Layout.png",
    "wordmark_dark": f"TIS Wordmark Only {_DASH} Dark Blue.png",
    "wordmark_white": f"TIS Wordmark Only {_DASH} White.png",
}

ORGANIZATION_LOGO_SLOTS = (
    {
        "slot_key": "primary",
        "label": "Main organization logo",
        "class_name": "logo-primary",
        "sort_order": 1,
        "show_in_brand_strip": True,
        "recommendation": "PNG with transparency; 600px wide for horizontal or 200px tall for stacked artwork.",
    },
    {
        "slot_key": "dark",
        "label": "Dark logo for light backgrounds",
        "class_name": "logo-dark",
        "sort_order": 2,
        "show_in_brand_strip": False,
        "recommendation": "Dark artwork on transparency; 600px wide for horizontal or 200px tall for stacked artwork.",
    },
    {
        "slot_key": "light",
        "label": "Light logo for dark backgrounds",
        "class_name": "logo-light",
        "sort_order": 3,
        "show_in_brand_strip": False,
        "recommendation": "White or light artwork on transparency; 600px wide for horizontal or 200px tall for stacked artwork.",
    },
    {
        "slot_key": "favicon",
        "label": "Organization favicon",
        "class_name": "logo-favicon",
        "sort_order": 4,
        "show_in_brand_strip": False,
        "recommendation": "Square PNG or WEBP; 512x512px recommended, 128x128px minimum.",
    },
    {
        "slot_key": "accreditation",
        "label": "Accreditation or partner logo",
        "class_name": "logo-accreditation",
        "sort_order": 5,
        "show_in_brand_strip": True,
        "recommendation": "PNG with transparency recommended; minimum 128x48px.",
    },
    {
        "slot_key": "secondary",
        "label": "Secondary organization logo",
        "class_name": "logo-secondary",
        "sort_order": 6,
        "show_in_brand_strip": True,
        "recommendation": "Optional secondary identity; PNG with transparency recommended.",
    },
)
ORGANIZATION_LOGO_SLOT_MAP = {
    slot["slot_key"]: slot for slot in ORGANIZATION_LOGO_SLOTS
}


class BrandingStorageError(ValueError):
    pass


@dataclass(frozen=True)
class LogoUploadInfo:
    extension: str
    content_type: str
    width: int
    height: int


class ProtectedBrandingStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        normalized = str(path or "").replace("\\", "/").lstrip("/")
        parts = PurePosixPath(normalized).parts
        blocked_prefixes = {
            ("branding", "organizations"),
            ("uploads", "school_group_logos"),
            ("uploads", "branch_logos"),
        }
        if len(parts) >= 2 and parts[:2] in blocked_prefixes:
            return Response(status_code=404)
        return await super().get_response(path, scope)


def _positive_id(value, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BrandingStorageError(f"{label} must be a positive integer.") from exc
    if parsed <= 0:
        raise BrandingStorageError(f"{label} must be a positive integer.")
    return parsed


def _safe_filename(filename: str) -> str:
    normalized = str(filename or "").strip()
    if (
        not normalized
        or Path(normalized).name != normalized
        or not re.fullmatch(r"[A-Za-z0-9._-]+", normalized)
    ):
        raise BrandingStorageError("Logo filename is invalid.")
    return normalized


def _relative_static_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(STATIC_ROOT.resolve())
    except ValueError as exc:
        raise BrandingStorageError("Branding path is outside the static root.") from exc
    return relative.as_posix()


def tis_logo_relative_path(
    *, theme: str = "light", layout: str = "horizontal", compact: bool = False
) -> str:
    normalized_theme = str(theme or "light").strip().lower()
    normalized_layout = str(layout or "horizontal").strip().lower()
    is_dark_background = normalized_theme in {"dark", "navy", "colored", "gradient"}
    if compact:
        key = "wordmark_white" if is_dark_background else "wordmark_dark"
    elif normalized_layout == "stacked":
        key = "light_stacked" if is_dark_background else "full_color_stacked"
    else:
        key = "light_horizontal" if is_dark_background else "full_color_horizontal"
    return _relative_static_path(TIS_LOGO_ROOT / TIS_LOGO_FILENAMES[key])


def tis_logo_absolute_path(
    *, theme: str = "light", layout: str = "horizontal", compact: bool = False
) -> Path:
    relative = PurePosixPath(
        tis_logo_relative_path(theme=theme, layout=layout, compact=compact)
    )
    return STATIC_ROOT / Path(*relative.parts)


def organization_root(school_group_id: int) -> Path:
    return ORGANIZATIONS_ROOT / str(_positive_id(school_group_id, "School group ID"))


def organization_logo_dir(school_group_id: int) -> Path:
    return organization_root(school_group_id) / "logos"


def branch_logo_dir(school_group_id: int, branch_id: int) -> Path:
    resolved_branch_id = _positive_id(branch_id, "Branch ID")
    return organization_root(school_group_id) / "branches" / str(resolved_branch_id) / "logos"


def ensure_organization_logo_dir(school_group_id: int) -> Path:
    target = organization_logo_dir(school_group_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_branch_logo_dir(school_group_id: int, branch_id: int) -> Path:
    target = branch_logo_dir(school_group_id, branch_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def organization_logo_relative_path(school_group_id: int, filename: str) -> str:
    return _relative_static_path(
        organization_logo_dir(school_group_id) / _safe_filename(filename)
    )


def branch_logo_relative_path(
    school_group_id: int, branch_id: int, filename: str
) -> str:
    return _relative_static_path(
        branch_logo_dir(school_group_id, branch_id) / _safe_filename(filename)
    )


def _normalized_relative_parts(relative_path: str) -> tuple[str, ...]:
    raw = str(relative_path or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/"):
        raise BrandingStorageError("Branding path must be relative.")
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise BrandingStorageError("Branding path is invalid.")
    return parts


def resolve_organization_asset_path(
    school_group_id: int, asset_path: str, *, require_file: bool = True
) -> Path:
    group_id = _positive_id(school_group_id, "School group ID")
    parts = _normalized_relative_parts(asset_path)
    is_group_logo = len(parts) == 2 and parts[0] == "logos"
    is_branch_logo = (
        len(parts) == 4
        and parts[0] == "branches"
        and parts[2] == "logos"
        and str(parts[1]).isdigit()
        and int(parts[1]) > 0
    )
    if not (is_group_logo or is_branch_logo):
        raise BrandingStorageError("Organization asset path is not an approved logo path.")
    _safe_filename(parts[-1])
    root = organization_root(group_id).resolve()
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise BrandingStorageError("Organization asset path escapes its tenant root.") from exc
    if require_file and not candidate.is_file():
        raise FileNotFoundError(str(candidate))
    return candidate


def organization_asset_subpath(
    school_group_id: int, static_relative_path: str
) -> str:
    group_id = _positive_id(school_group_id, "School group ID")
    parts = _normalized_relative_parts(static_relative_path)
    prefix = ("branding", "organizations", str(group_id))
    if parts[:3] != prefix:
        raise BrandingStorageError("Logo does not belong to the selected organization.")
    subpath = PurePosixPath(*parts[3:]).as_posix()
    resolve_organization_asset_path(group_id, subpath, require_file=False)
    return subpath


def can_access_organization_assets(
    requesting_school_group_id: int | None,
    target_school_group_id: int,
    *,
    can_manage_all: bool = False,
) -> bool:
    if can_manage_all:
        return True
    try:
        return _positive_id(
            requesting_school_group_id, "Requesting school group ID"
        ) == _positive_id(target_school_group_id, "Target school group ID")
    except BrandingStorageError:
        return False


def resolve_owned_logo_path(
    image_path: str,
    *,
    school_group_id: int,
    branch_id: int | None = None,
    allow_legacy: bool = True,
    require_file: bool = True,
) -> Path:
    group_id = _positive_id(school_group_id, "School group ID")
    parts = _normalized_relative_parts(image_path)
    if branch_id is None:
        expected_prefix = ("branding", "organizations", str(group_id), "logos")
        legacy_prefix = ("uploads", "school_group_logos", str(group_id))
    else:
        resolved_branch_id = _positive_id(branch_id, "Branch ID")
        expected_prefix = (
            "branding",
            "organizations",
            str(group_id),
            "branches",
            str(resolved_branch_id),
            "logos",
        )
        legacy_prefix = ("uploads", "branch_logos", str(resolved_branch_id))
    is_owned = parts[:-1] == expected_prefix
    is_owned_legacy = allow_legacy and parts[:-1] == legacy_prefix
    if not (is_owned or is_owned_legacy):
        raise BrandingStorageError(
            "Logo path does not belong to the requested tenant scope."
        )
    _safe_filename(parts[-1])
    candidate = (STATIC_ROOT / Path(*parts)).resolve()
    try:
        candidate.relative_to(STATIC_ROOT.resolve())
    except ValueError as exc:
        raise BrandingStorageError("Logo path escapes the static root.") from exc
    if require_file and not candidate.is_file():
        raise FileNotFoundError(str(candidate))
    return candidate


def write_logo_file(
    file_bytes: bytes,
    *,
    school_group_id: int,
    slot_key: str,
    extension: str,
    branch_id: int | None = None,
) -> str:
    normalized_slot = str(slot_key or "").strip().lower()
    if normalized_slot not in ORGANIZATION_LOGO_SLOT_MAP:
        raise BrandingStorageError("Logo slot is invalid.")
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension not in ALLOWED_LOGO_EXTENSIONS:
        raise BrandingStorageError("Logo extension is invalid.")
    filename = f"{normalized_slot}_{time.time_ns()}{normalized_extension}"
    if branch_id is None:
        target_dir = ensure_organization_logo_dir(school_group_id)
        relative_path = organization_logo_relative_path(school_group_id, filename)
    else:
        target_dir = ensure_branch_logo_dir(school_group_id, branch_id)
        relative_path = branch_logo_relative_path(
            school_group_id, branch_id, filename
        )
    target = target_dir / filename
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(file_bytes)
    os.replace(temporary, target)
    return relative_path


def delete_owned_logo_file(
    image_path: str,
    *,
    school_group_id: int,
    branch_id: int | None = None,
) -> bool:
    try:
        target = resolve_owned_logo_path(
            image_path,
            school_group_id=school_group_id,
            branch_id=branch_id,
            allow_legacy=True,
            require_file=False,
        )
    except BrandingStorageError:
        return False
    if not target.exists():
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True


def migrate_legacy_logo_file(
    image_path: str,
    *,
    school_group_id: int,
    branch_id: int | None = None,
) -> str:
    try:
        resolve_owned_logo_path(
            image_path,
            school_group_id=school_group_id,
            branch_id=branch_id,
            allow_legacy=False,
            require_file=False,
        )
        return PurePosixPath(*_normalized_relative_parts(image_path)).as_posix()
    except BrandingStorageError:
        pass

    source = resolve_owned_logo_path(
        image_path,
        school_group_id=school_group_id,
        branch_id=branch_id,
        allow_legacy=True,
        require_file=True,
    )
    if branch_id is None:
        target_dir = ensure_organization_logo_dir(school_group_id)

        def relative_builder(name: str) -> str:
            return organization_logo_relative_path(school_group_id, name)
    else:
        target_dir = ensure_branch_logo_dir(school_group_id, branch_id)

        def relative_builder(name: str) -> str:
            return branch_logo_relative_path(school_group_id, branch_id, name)

    target = target_dir / _safe_filename(source.name)
    if target.exists() and target.read_bytes() != source.read_bytes():
        target = target_dir / f"legacy_{time.time_ns()}_{source.name}"
    if not target.exists():
        shutil.copy2(source, target)
    return relative_builder(target.name)


def copy_legacy_default_logo(
    source: Path,
    *,
    school_group_id: int,
    filename: str,
) -> str:
    if not source.is_file():
        raise FileNotFoundError(str(source))
    target_dir = ensure_organization_logo_dir(school_group_id)
    target = target_dir / _safe_filename(filename)
    if not target.exists():
        shutil.copy2(source, target)
    return organization_logo_relative_path(school_group_id, target.name)


def _svg_dimensions(root: ElementTree.Element) -> tuple[int, int]:
    view_box = str(
        root.attrib.get("viewBox") or root.attrib.get("viewbox") or ""
    ).strip()
    if view_box:
        parts = re.split(r"[\s,]+", view_box)
        if len(parts) == 4:
            try:
                width = int(round(float(parts[2])))
                height = int(round(float(parts[3])))
                if width > 0 and height > 0:
                    return width, height
            except ValueError:
                pass

    def numeric_dimension(value: str) -> int:
        match = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*", str(value or "")
        )
        return int(round(float(match.group(1)))) if match else 0

    width = numeric_dimension(root.attrib.get("width", ""))
    height = numeric_dimension(root.attrib.get("height", ""))
    if width <= 0 or height <= 0:
        raise BrandingStorageError(
            "SVG logos require valid width/height or viewBox dimensions."
        )
    return width, height


def _validate_svg(file_bytes: bytes) -> tuple[int, int]:
    lowered = file_bytes[:4096].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise BrandingStorageError(
            "SVG document declarations and entities are not allowed."
        )
    try:
        root = ElementTree.fromstring(file_bytes)
    except (ElementTree.ParseError, ValueError) as exc:
        raise BrandingStorageError("SVG logo is not valid XML.") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise BrandingStorageError(
            "Uploaded SVG does not contain an SVG root element."
        )
    blocked_tags = {
        "script",
        "foreignobject",
        "iframe",
        "object",
        "embed",
        "audio",
        "video",
    }
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() in blocked_tags:
            raise BrandingStorageError("SVG contains an unsafe element.")
        for attribute, raw_value in element.attrib.items():
            attribute_name = attribute.rsplit("}", 1)[-1].lower()
            value = str(raw_value or "").strip().lower()
            if attribute_name.startswith("on") or "javascript:" in value:
                raise BrandingStorageError("SVG contains an unsafe attribute.")
            if (
                attribute_name in {"href", "src"}
                and value
                and not value.startswith(("#", "data:image/"))
            ):
                raise BrandingStorageError(
                    "SVG external resources are not allowed."
                )
            if attribute_name == "style" and "url(" in value:
                raise BrandingStorageError(
                    "SVG external style resources are not allowed."
                )
    return _svg_dimensions(root)


def _validate_minimum_dimensions(slot_key: str, width: int, height: int):
    if width <= 0 or height <= 0 or width * height > MAX_LOGO_PIXELS:
        raise BrandingStorageError("Logo dimensions are invalid or too large.")
    if slot_key == "favicon":
        if width < 128 or height < 128:
            raise BrandingStorageError("Favicons must be at least 128x128px.")
        ratio = width / height
        if ratio < 0.75 or ratio > 1.34:
            raise BrandingStorageError(
                "Favicons must use a square or near-square aspect ratio."
            )
        return
    if width < 128 or height < 48:
        raise BrandingStorageError("Logos must be at least 128x48px.")


def validate_logo_upload(
    file_bytes: bytes,
    filename: str,
    *,
    slot_key: str,
) -> LogoUploadInfo:
    if slot_key not in ORGANIZATION_LOGO_SLOT_MAP:
        raise BrandingStorageError("Logo slot is invalid.")
    if not file_bytes:
        raise BrandingStorageError("Choose a logo file to upload.")
    if len(file_bytes) > LOGO_MAX_BYTES:
        raise BrandingStorageError(
            "Logo file is too large. Maximum size is 4 MB."
        )

    stripped = file_bytes.lstrip()
    lowered_name = str(filename or "").strip().lower()
    if stripped.startswith((b"<svg", b"<?xml")) or lowered_name.endswith(".svg"):
        width, height = _validate_svg(file_bytes)
        extension = ".svg"
        content_type = "image/svg+xml"
    else:
        try:
            with Image.open(io.BytesIO(file_bytes)) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise BrandingStorageError(
                "Upload a valid PNG, JPG, WEBP, or safe SVG logo."
            ) from exc
        format_map = {
            "PNG": (".png", "image/png"),
            "JPEG": (".jpg", "image/jpeg"),
            "WEBP": (".webp", "image/webp"),
        }
        if image_format not in format_map:
            raise BrandingStorageError(
                "Upload a PNG, JPG, WEBP, or safe SVG logo."
            )
        extension, content_type = format_map[image_format]

    _validate_minimum_dimensions(slot_key, int(width), int(height))
    return LogoUploadInfo(
        extension=extension,
        content_type=content_type,
        width=int(width),
        height=int(height),
    )
