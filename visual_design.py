import json
import re
from dataclasses import dataclass
from html import escape


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class VisualDesignSetting:
    key: str
    label: str
    input_type: str
    css_property: str = ""
    default: str = ""
    options: tuple[str, ...] = ()
    min_value: int | None = None
    max_value: int | None = None
    unit: str = ""
    selector_suffix: str = ""


@dataclass(frozen=True)
class VisualDesignComponent:
    key: str
    label: str
    page_key: str
    component_type: str
    settings: tuple[VisualDesignSetting, ...]


CARD_SETTINGS = (
    VisualDesignSetting("width", "Width", "number", "width", "", min_value=160, max_value=1200, unit="px"),
    VisualDesignSetting("min_height", "Minimum Height", "number", "min-height", "", min_value=40, max_value=800, unit="px"),
    VisualDesignSetting("padding", "Padding", "number", "padding", "", min_value=0, max_value=80, unit="px"),
    VisualDesignSetting("margin", "Margin", "number", "margin", "", min_value=0, max_value=80, unit="px"),
    VisualDesignSetting("background", "Background", "color", "background-color"),
    VisualDesignSetting("border_radius", "Border Radius", "number", "border-radius", "", min_value=0, max_value=48, unit="px"),
    VisualDesignSetting("border_color", "Border Color", "color", "border-color"),
    VisualDesignSetting("shadow", "Shadow", "select", "box-shadow", options=("default", "none", "soft", "deep")),
    VisualDesignSetting("title_size", "Title Size", "number", "font-size", "", min_value=12, max_value=56, unit="px", selector_suffix=" strong"),
    VisualDesignSetting("text_size", "Text Size", "number", "font-size", "", min_value=10, max_value=24, unit="px", selector_suffix=" small"),
    VisualDesignSetting("icon_size", "Icon Size", "number", "width", "", min_value=12, max_value=42, unit="px", selector_suffix=" svg[data-tis-icon]"),
    VisualDesignSetting("alignment", "Alignment", "select", "text-align", options=("default", "left", "center", "right")),
    VisualDesignSetting("order", "Order", "number", "order", "", min_value=0, max_value=20),
    VisualDesignSetting("visibility", "Visibility", "select", "display", options=("visible", "hidden")),
)

BUTTON_SETTINGS = (
    VisualDesignSetting("width", "Width", "number", "width", "", min_value=40, max_value=420, unit="px"),
    VisualDesignSetting("height", "Height", "number", "min-height", "", min_value=28, max_value=96, unit="px"),
    VisualDesignSetting("padding", "Padding", "number", "padding", "", min_value=0, max_value=40, unit="px"),
    VisualDesignSetting("background", "Color", "color", "background-color"),
    VisualDesignSetting("radius", "Radius", "number", "border-radius", "", min_value=0, max_value=40, unit="px"),
    VisualDesignSetting("text_size", "Text Size", "number", "font-size", "", min_value=10, max_value=28, unit="px"),
    VisualDesignSetting("alignment", "Alignment", "select", "justify-content", options=("default", "flex-start", "center", "flex-end")),
    VisualDesignSetting("icon_size", "Icon Size", "number", "width", "", min_value=10, max_value=36, unit="px", selector_suffix=" svg[data-tis-icon]"),
    VisualDesignSetting("visibility", "Visibility", "select", "display", options=("visible", "hidden")),
)

SECTION_SETTINGS = (
    VisualDesignSetting("width", "Width", "number", "width", "", min_value=160, max_value=1600, unit="px"),
    VisualDesignSetting("min_height", "Minimum Height", "number", "min-height", "", min_value=30, max_value=1000, unit="px"),
    VisualDesignSetting("columns", "Columns", "number", "grid-template-columns", "", min_value=1, max_value=6),
    VisualDesignSetting("gap", "Spacing", "number", "gap", "", min_value=0, max_value=80, unit="px"),
    VisualDesignSetting("padding", "Padding", "number", "padding", "", min_value=0, max_value=80, unit="px"),
    VisualDesignSetting("density", "Density", "select", "", options=("default", "compact", "comfortable")),
    VisualDesignSetting("visibility", "Visibility", "select", "display", options=("visible", "hidden")),
)

NAV_SETTINGS = (
    VisualDesignSetting("width", "Width", "number", "width", "", min_value=220, max_value=420, unit="px"),
    VisualDesignSetting("min_height", "Minimum Height", "number", "min-height", "", min_value=120, max_value=1200, unit="px"),
    VisualDesignSetting("item_spacing", "Item Spacing", "number", "gap", "", min_value=0, max_value=28, unit="px"),
    VisualDesignSetting("item_padding", "Item Padding", "number", "padding", "", min_value=4, max_value=28, unit="px", selector_suffix=" .sidebar-link"),
    VisualDesignSetting("icon_size", "Icon Size", "number", "width", "", min_value=12, max_value=34, unit="px", selector_suffix=" svg[data-tis-icon]"),
    VisualDesignSetting("active_background", "Active Background", "color", "background-color", selector_suffix=" .sidebar-link.is-active"),
)

TABLE_SETTINGS = (
    VisualDesignSetting("width", "Width", "number", "width", "", min_value=200, max_value=1600, unit="px"),
    VisualDesignSetting("min_height", "Minimum Height", "number", "min-height", "", min_value=60, max_value=1000, unit="px"),
    VisualDesignSetting("row_height", "Row Height", "number", "height", "", min_value=28, max_value=80, unit="px", selector_suffix=" tbody tr"),
    VisualDesignSetting("density", "Density", "select", "", options=("default", "compact", "comfortable")),
    VisualDesignSetting("border_color", "Border Color", "color", "border-color"),
    VisualDesignSetting("header_background", "Header Background", "color", "background-color", selector_suffix=" thead"),
)

UNIVERSAL_SETTINGS = (
    VisualDesignSetting("width", "Width", "number", "width", "", min_value=10, max_value=1800, unit="px"),
    VisualDesignSetting("min_height", "Minimum Height", "number", "min-height", "", min_value=10, max_value=1400, unit="px"),
    VisualDesignSetting("padding", "Padding", "number", "padding", "", min_value=0, max_value=120, unit="px"),
    VisualDesignSetting("margin", "Margin", "number", "margin", "", min_value=0, max_value=120, unit="px"),
    VisualDesignSetting("background", "Background", "color", "background-color"),
    VisualDesignSetting("color", "Text Color", "color", "color"),
    VisualDesignSetting("border_radius", "Border Radius", "number", "border-radius", "", min_value=0, max_value=80, unit="px"),
    VisualDesignSetting("border_color", "Border Color", "color", "border-color"),
    VisualDesignSetting("border_width", "Border Width", "number", "border-width", "", min_value=0, max_value=16, unit="px"),
    VisualDesignSetting("shadow", "Shadow", "select", "box-shadow", options=("default", "none", "soft", "deep")),
    VisualDesignSetting("text_size", "Text Size", "number", "font-size", "", min_value=8, max_value=72, unit="px"),
    VisualDesignSetting("alignment", "Alignment", "select", "text-align", options=("default", "left", "center", "right")),
    VisualDesignSetting("order", "Order", "number", "order", "", min_value=0, max_value=100),
    VisualDesignSetting("visibility", "Visibility", "select", "display", options=("visible", "hidden")),
)


VISUAL_DESIGN_COMPONENTS: tuple[VisualDesignComponent, ...] = (
    VisualDesignComponent("shell.sidebar", "Sidebar", "global", "navigation", NAV_SETTINGS),
    VisualDesignComponent("shell.navigation", "Navigation Items", "global", "navigation", NAV_SETTINGS[1:]),
    VisualDesignComponent("shell.header", "Page Header", "global", "section", SECTION_SETTINGS),
    VisualDesignComponent("shell.page_stage", "Page Stage", "global", "section", SECTION_SETTINGS),
    VisualDesignComponent("dashboard.kpi_grid", "Dashboard KPI Section", "dashboard", "section", SECTION_SETTINGS),
    VisualDesignComponent("dashboard.subjects_card", "Subjects Card", "dashboard", "card", CARD_SETTINGS),
    VisualDesignComponent("dashboard.teachers_card", "Teachers Card", "dashboard", "card", CARD_SETTINGS),
    VisualDesignComponent("dashboard.workspace", "Dashboard Workspace", "dashboard", "section", SECTION_SETTINGS),
    VisualDesignComponent("dashboard.tabs", "Dashboard Tabs", "dashboard", "section", SECTION_SETTINGS),
    VisualDesignComponent("dashboard.subjects_panel", "Subjects Panel", "dashboard", "section", SECTION_SETTINGS),
    VisualDesignComponent("dashboard.subjects_table", "Subjects Table", "dashboard", "table", TABLE_SETTINGS),
    VisualDesignComponent("dashboard.export_button", "Export Button", "dashboard", "button", BUTTON_SETTINGS),
)

VISUAL_COMPONENT_MAP = {component.key: component for component in VISUAL_DESIGN_COMPONENTS}
UNIVERSAL_COMPONENT_KEY_PREFIX = "custom."


def get_components_for_page(page_key: str) -> list[VisualDesignComponent]:
    normalized_page = str(page_key or "").strip()
    return [
        component
        for component in VISUAL_DESIGN_COMPONENTS
        if component.page_key in ("global", normalized_page)
    ]


def _setting_map(component: VisualDesignComponent) -> dict[str, VisualDesignSetting]:
    return {setting.key: setting for setting in component.settings}


def is_custom_component_key(component_key: str) -> bool:
    return str(component_key or "").strip().startswith(UNIVERSAL_COMPONENT_KEY_PREFIX)


def get_component_settings(component_key: str, component_type: str = "") -> tuple[VisualDesignSetting, ...]:
    component = VISUAL_COMPONENT_MAP.get(str(component_key or "").strip())
    if component:
        return component.settings
    if is_custom_component_key(component_key):
        normalized_type = str(component_type or "").strip().lower()
        if normalized_type == "button":
            return BUTTON_SETTINGS + UNIVERSAL_SETTINGS
        if normalized_type == "table":
            return TABLE_SETTINGS + UNIVERSAL_SETTINGS
        if normalized_type == "navigation":
            return NAV_SETTINGS + UNIVERSAL_SETTINGS
        if normalized_type == "section":
            return SECTION_SETTINGS + UNIVERSAL_SETTINGS
        return UNIVERSAL_SETTINGS
    return ()


def _settings_by_key(component_key: str, component_type: str = "") -> dict[str, VisualDesignSetting]:
    return {setting.key: setting for setting in get_component_settings(component_key, component_type)}


def validate_visual_design_value(setting: VisualDesignSetting, raw_value) -> str:
    value = str(raw_value or "").strip()
    if setting.input_type == "color":
        if not value:
            return ""
        if HEX_COLOR_RE.match(value):
            return value.upper()
        raise ValueError(f"{setting.label} must be a valid hex color.")
    if setting.input_type == "select":
        if value in setting.options:
            return value
        if not value and "default" in setting.options:
            return "default"
        raise ValueError(f"{setting.label} has an invalid option.")
    if setting.input_type == "number":
        if not value:
            return ""
        if setting.unit and value.endswith(setting.unit):
            value = value[:-len(setting.unit)].strip()
        try:
            numeric_value = int(value)
        except ValueError as exc:
            raise ValueError(f"{setting.label} must be a number.") from exc
        if setting.min_value is not None and numeric_value < setting.min_value:
            raise ValueError(f"{setting.label} must be at least {setting.min_value}.")
        if setting.max_value is not None and numeric_value > setting.max_value:
            raise ValueError(f"{setting.label} must be at most {setting.max_value}.")
        if setting.key == "columns":
            return str(numeric_value)
        return f"{numeric_value}{setting.unit}"
    return value


def normalize_visual_payload(component_key: str, settings_payload: dict, component_type: str = "") -> dict[str, str]:
    normalized_component_key = str(component_key or "").strip()
    allowed_settings = _settings_by_key(normalized_component_key, component_type)
    if not allowed_settings:
        raise ValueError("Unknown design component.")
    normalized = {}
    for key, raw_value in (settings_payload or {}).items():
        setting = allowed_settings.get(str(key or "").strip())
        if not setting:
            continue
        value = validate_visual_design_value(setting, raw_value)
        if value:
            normalized[setting.key] = value
    return normalized


def rows_to_visual_settings(rows) -> dict[str, dict[str, str]]:
    settings = {}
    for row in rows:
        if not getattr(row, "is_active", True):
            continue
        component_key = str(getattr(row, "component_key", "") or "")
        component_type = str(getattr(row, "component_type", "") or "")
        allowed_settings = _settings_by_key(component_key, component_type)
        if not allowed_settings:
            continue
        setting = allowed_settings.get(str(getattr(row, "setting_key", "") or ""))
        if not setting:
            continue
        try:
            value = validate_visual_design_value(setting, getattr(row, "setting_value", ""))
        except ValueError:
            continue
        if value:
            settings.setdefault(component_key, {})[setting.key] = value
    return settings


def _css_value(setting: VisualDesignSetting, value: str) -> str:
    if setting.key == "visibility":
        return "none" if value == "hidden" else ""
    if setting.key == "shadow":
        if value == "none":
            return "none"
        if value == "soft":
            return "0 10px 24px rgba(15, 23, 42, .08)"
        if value == "deep":
            return "0 18px 42px rgba(15, 23, 42, .16)"
        return ""
    if setting.key == "columns":
        return f"repeat({value}, minmax(0, 1fr))"
    return value


def build_visual_design_css(settings_by_component: dict[str, dict[str, str]]) -> str:
    rules = []
    for component_key, settings in (settings_by_component or {}).items():
        component = VISUAL_COMPONENT_MAP.get(component_key)
        if component:
            setting_lookup = _setting_map(component)
        elif is_custom_component_key(component_key):
            setting_lookup = _settings_by_key(component_key)
        else:
            continue
        declarations_by_suffix: dict[str, list[str]] = {}
        for setting_key, value in settings.items():
            setting = setting_lookup.get(setting_key)
            if not setting or not setting.css_property:
                continue
            css_value = _css_value(setting, value)
            if not css_value:
                continue
            declarations_by_suffix.setdefault(setting.selector_suffix, []).append(
                f"{setting.css_property}: {css_value};"
            )
        for suffix, declarations in declarations_by_suffix.items():
            selector = f'[data-design-component="{escape(component_key)}"]{suffix}'
            rules.append(f"{selector} {{ {' '.join(declarations)} }}")
    return "\n".join(rules)


def build_visual_design_config(page_key: str, settings_by_component: dict[str, dict[str, str]]) -> dict:
    components = []
    for component in get_components_for_page(page_key):
        components.append(
            {
                "key": component.key,
                "label": component.label,
                "page_key": component.page_key,
                "component_type": component.component_type,
                "settings": [
                    {
                        "key": setting.key,
                        "label": setting.label,
                        "input_type": setting.input_type,
                        "default": setting.default,
                        "options": list(setting.options),
                        "min_value": setting.min_value,
                        "max_value": setting.max_value,
                        "unit": setting.unit,
                        "css_property": setting.css_property,
                        "selector_suffix": setting.selector_suffix,
                    }
                    for setting in component.settings
                ],
            }
        )
    return {
        "page_key": page_key,
        "components": components,
        "saved_settings": settings_by_component or {},
    }


def config_json(config: dict) -> str:
    return json.dumps(config or {}, separators=(",", ":"))
