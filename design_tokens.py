import re
from dataclasses import dataclass


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class DesignToken:
    key: str
    label: str
    css_variable: str
    default: str
    input_type: str
    group: str
    help_text: str = ""
    options: tuple[str, ...] = ()
    min_value: int | None = None
    max_value: int | None = None
    unit: str = ""


DESIGN_TOKENS: tuple[DesignToken, ...] = (
    DesignToken("app_bg", "Background", "--app-bg", "#f5f7fb", "color", "Colors"),
    DesignToken("app_surface", "Surface", "--app-surface-strong", "#ffffff", "color", "Colors"),
    DesignToken("app_line", "Border", "--app-line", "#d8e0ec", "color", "Colors"),
    DesignToken("app_ink", "Text", "--app-ink", "#172033", "color", "Colors"),
    DesignToken("app_muted", "Muted Text", "--app-muted", "#667085", "color", "Colors"),
    DesignToken("app_brand", "Primary", "--app-brand", "#1f4f82", "color", "Colors"),
    DesignToken("app_accent", "Accent", "--app-accent", "#8a6f2a", "color", "Colors"),
    DesignToken("app_success", "Success", "--app-success", "#2f6f5e", "color", "Colors"),
    DesignToken("app_warning", "Warning", "--app-warning", "#9a6a20", "color", "Colors"),
    DesignToken("app_danger", "Danger", "--app-danger", "#a23b32", "color", "Colors"),
    DesignToken("base_font_size", "Base Font Size", "--tis-base-font-size", "14px", "number", "Typography", min_value=12, max_value=18, unit="px"),
    DesignToken("spacing_scale", "Spacing Scale", "--tis-spacing-scale", "1", "select", "Spacing", options=("0.85", "1", "1.15")),
    DesignToken("card_radius", "Card Radius", "--app-radius-md", "12px", "number", "Cards", min_value=4, max_value=24, unit="px"),
    DesignToken("button_radius", "Button Radius", "--tis-button-radius", "8px", "number", "Buttons", min_value=4, max_value=20, unit="px"),
    DesignToken("sidebar_width", "Sidebar Width", "--tis-sidebar-width", "292px", "number", "Sidebar", min_value=240, max_value=360, unit="px"),
)

DESIGN_TOKEN_MAP = {token.key: token for token in DESIGN_TOKENS}


def default_design_settings() -> dict[str, str]:
    return {token.key: token.default for token in DESIGN_TOKENS}


def validate_design_token_value(token: DesignToken, raw_value) -> str:
    value = str(raw_value or "").strip()
    if token.input_type == "color":
        if HEX_COLOR_RE.match(value):
            return value.upper()
        raise ValueError(f"{token.label} must be a valid hex color.")
    if token.input_type == "select":
        if value in token.options:
            return value
        raise ValueError(f"{token.label} has an invalid option.")
    if token.input_type == "number":
        if token.unit and value.endswith(token.unit):
            value = value[:-len(token.unit)].strip()
        try:
            numeric_value = int(value)
        except ValueError as exc:
            raise ValueError(f"{token.label} must be a number.") from exc
        if token.min_value is not None and numeric_value < token.min_value:
            raise ValueError(f"{token.label} must be at least {token.min_value}.")
        if token.max_value is not None and numeric_value > token.max_value:
            raise ValueError(f"{token.label} must be at most {token.max_value}.")
        return f"{numeric_value}{token.unit}"
    return token.default


def merge_design_settings(rows) -> dict[str, str]:
    settings = default_design_settings()
    for row in rows:
        token = DESIGN_TOKEN_MAP.get(str(getattr(row, "key", "") or ""))
        if not token:
            continue
        try:
            settings[token.key] = validate_design_token_value(token, getattr(row, "value", ""))
        except ValueError:
            settings[token.key] = token.default
    return settings


def build_design_css(settings: dict[str, str]) -> str:
    declarations = []
    for token in DESIGN_TOKENS:
        value = settings.get(token.key, token.default)
        declarations.append(f"{token.css_variable}: {value};")
    return ":root { " + " ".join(declarations) + " }"
