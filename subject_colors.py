import colorsys
import hashlib
import re

DEFAULT_SUBJECT_COLOR = "#0A4EA3"
HEX_COLOR_PATTERN = re.compile(r"^#?[0-9A-Fa-f]{6}$")
PREFIX_HUE_HINTS = {
    "ENG": 212,
    "MAT": 38,
    "SCI": 165,
    "BIO": 145,
    "CHE": 18,
    "PHY": 250,
    "ICT": 198,
    "COM": 192,
    "ARA": 126,
    "ARB": 126,
    "ISL": 98,
    "SOC": 22,
    "HIS": 8,
    "GEO": 182,
    "ART": 314,
    "MUS": 286,
    "PE": 344,
}


def normalize_subject_code(value) -> str:
    if value is None:
        return ""
    return "".join(str(value).strip().upper().split())


def normalize_hex_color(value) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if not HEX_COLOR_PATTERN.fullmatch(cleaned):
        return None
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    return cleaned.upper()


def _rgb_to_hex(red: float, green: float, blue: float) -> str:
    safe_red = max(0, min(255, int(round(red))))
    safe_green = max(0, min(255, int(round(green))))
    safe_blue = max(0, min(255, int(round(blue))))
    return f"#{safe_red:02X}{safe_green:02X}{safe_blue:02X}"


def hex_to_rgb(color_value: str) -> tuple[int, int, int]:
    cleaned = normalize_hex_color(color_value) or DEFAULT_SUBJECT_COLOR
    return (
        int(cleaned[1:3], 16),
        int(cleaned[3:5], 16),
        int(cleaned[5:7], 16),
    )


def blend_hex_colors(start_color: str, end_color: str, ratio: float) -> str:
    safe_ratio = max(0.0, min(1.0, float(ratio)))
    start_rgb = hex_to_rgb(start_color)
    end_rgb = hex_to_rgb(end_color)
    return _rgb_to_hex(
        start_rgb[0] + (end_rgb[0] - start_rgb[0]) * safe_ratio,
        start_rgb[1] + (end_rgb[1] - start_rgb[1]) * safe_ratio,
        start_rgb[2] + (end_rgb[2] - start_rgb[2]) * safe_ratio,
    )


def _subject_color_from_token(token: str, prefix_seed: str) -> str:
    if not token:
        return DEFAULT_SUBJECT_COLOR

    prefix = re.sub(r"[^A-Z]", "", prefix_seed)[:3]
    digest = hashlib.sha1(token.encode("utf-8")).hexdigest()

    hue_seed = int(digest[:8], 16)
    saturation_seed = int(digest[8:16], 16)
    lightness_seed = int(digest[16:24], 16)

    base_hue = PREFIX_HUE_HINTS.get(prefix, hue_seed % 360)
    hue_offset = ((hue_seed // 360) % 21) - 10
    hue = (base_hue + hue_offset) % 360

    saturation = 0.52 + (saturation_seed % 14) / 100
    lightness = 0.42 + (lightness_seed % 10) / 100

    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, lightness, saturation)
    return _rgb_to_hex(red * 255, green * 255, blue * 255)


def _subject_identity_token(subject_code: str, subject_name: str | None = None) -> str:
    normalized_name = " ".join(str(subject_name or "").strip().upper().split())
    if normalized_name:
        return normalized_name

    normalized_code = normalize_subject_code(subject_code)
    if not normalized_code:
        return ""

    code_letters = re.sub(r"[^A-Z]", "", normalized_code)
    return code_letters or normalized_code


def generate_subject_color(subject_code: str, subject_name: str | None = None) -> str:
    identity_token = _subject_identity_token(subject_code, subject_name=subject_name)
    return _subject_color_from_token(identity_token, identity_token)


def generate_subject_color_by_code(subject_code: str) -> str:
    normalized_code = normalize_subject_code(subject_code)
    return _subject_color_from_token(normalized_code, normalized_code)


def resolve_subject_color(
    subject_code: str,
    stored_color: str | None = None,
    subject_name: str | None = None,
) -> str:
    return normalize_hex_color(stored_color) or generate_subject_color(
        subject_code,
        subject_name=subject_name,
    )


def build_subject_theme(color_value: str | None) -> dict[str, str]:
    accent = resolve_subject_color("", color_value)
    return {
        "accent": accent,
        "soft": blend_hex_colors(accent, "#FFFFFF", 0.86),
        "surface": blend_hex_colors(accent, "#F8FBFF", 0.91),
        "border": blend_hex_colors(accent, "#FFFFFF", 0.54),
        "text": blend_hex_colors(accent, "#0F172A", 0.18),
        "strong_text": blend_hex_colors(accent, "#0F172A", 0.08),
    }


def to_excel_hex(color_value: str | None) -> str:
    return resolve_subject_color("", color_value).lstrip("#").upper()
