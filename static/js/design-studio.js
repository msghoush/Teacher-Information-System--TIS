(function () {
    const configEl = document.getElementById("tis-design-studio-config");
    if (!configEl) return;

    let config = {};
    try {
        config = JSON.parse(configEl.textContent || "{}");
    } catch (error) {
        config = {};
    }

    const components = new Map((config.components || []).map((component) => [component.key, component]));
    const savedSettings = config.saved_settings || {};
    const isEnabled = document.body.classList.contains("design-studio-enabled");
    const pageKey = config.page_key || document.body.getAttribute("data-page-key") || "global";
    let selectedElement = null;
    let selectedComponent = null;
    const universalSettings = [
        {key: "width", label: "Width", input_type: "number", css_property: "width", min_value: 10, max_value: 1800, unit: "px"},
        {key: "min_height", label: "Height", input_type: "number", css_property: "min-height", min_value: 10, max_value: 1400, unit: "px"},
        {key: "padding", label: "Padding", input_type: "number", css_property: "padding", min_value: 0, max_value: 120, unit: "px"},
        {key: "margin", label: "Margin", input_type: "number", css_property: "margin", min_value: 0, max_value: 120, unit: "px"},
        {key: "background", label: "Background", input_type: "color", css_property: "background-color"},
        {key: "color", label: "Text Color", input_type: "color", css_property: "color"},
        {key: "border_radius", label: "Border Radius", input_type: "number", css_property: "border-radius", min_value: 0, max_value: 80, unit: "px"},
        {key: "border_color", label: "Border Color", input_type: "color", css_property: "border-color"},
        {key: "border_width", label: "Border Width", input_type: "number", css_property: "border-width", min_value: 0, max_value: 16, unit: "px"},
        {key: "shadow", label: "Shadow", input_type: "select", css_property: "box-shadow", options: ["default", "none", "soft", "deep"]},
        {key: "text_size", label: "Text Size", input_type: "number", css_property: "font-size", min_value: 8, max_value: 72, unit: "px"},
        {key: "alignment", label: "Alignment", input_type: "select", css_property: "text-align", options: ["default", "left", "center", "right"]},
        {key: "order", label: "Order", input_type: "number", css_property: "order", min_value: 0, max_value: 100},
        {key: "visibility", label: "Visibility", input_type: "select", css_property: "display", options: ["visible", "hidden"]},
    ];

    const icons = {
        adjust: '<svg viewBox="0 0 24 24"><path d="M4 7h10"></path><path d="M18 7h2"></path><circle cx="16" cy="7" r="2"></circle><path d="M4 17h2"></path><path d="M10 17h10"></path><circle cx="8" cy="17" r="2"></circle></svg>',
        select: '<svg viewBox="0 0 24 24"><path d="m5 3 14 8-7 2-3 7Z"></path></svg>',
        resize: '<svg viewBox="0 0 24 24"><path d="M4 14v6h6"></path><path d="M20 10V4h-6"></path><path d="M14 4h6v6"></path><path d="M10 20H4v-6"></path></svg>',
        save: '<svg viewBox="0 0 24 24"><path d="M5 21h14a2 2 0 0 0 2-2V7.5L16.5 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2Z"></path><path d="M17 21v-8H7v8"></path><path d="M7 3v5h8"></path></svg>',
        reset: '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7"></path><path d="M3 4v6h6"></path></svg>',
        hide: '<svg viewBox="0 0 24 24"><path d="M3 3l18 18"></path><path d="M10.6 10.6A2 2 0 0 0 13.4 13.4"></path><path d="M9.9 4.2A10.7 10.7 0 0 1 12 4c6.5 0 10 8 10 8a17.8 17.8 0 0 1-3.1 4.4"></path><path d="M6.6 6.6C3.6 8.6 2 12 2 12s3.5 8 10 8a10.8 10.8 0 0 0 4.5-1"></path></svg>',
        alignLeft: '<svg viewBox="0 0 24 24"><path d="M4 6h16"></path><path d="M4 10h10"></path><path d="M4 14h16"></path><path d="M4 18h10"></path></svg>',
        alignCenter: '<svg viewBox="0 0 24 24"><path d="M4 6h16"></path><path d="M7 10h10"></path><path d="M4 14h16"></path><path d="M7 18h10"></path></svg>',
        alignRight: '<svg viewBox="0 0 24 24"><path d="M4 6h16"></path><path d="M10 10h10"></path><path d="M4 14h16"></path><path d="M10 18h10"></path></svg>',
        close: '<svg viewBox="0 0 24 24"><path d="m6 6 12 12"></path><path d="m18 6-12 12"></path></svg>',
        resetAll: '<svg viewBox="0 0 24 24"><path d="M4 4v6h6"></path><path d="M20 20v-6h-6"></path><path d="M5 15a7 7 0 0 0 11.9 3.9L20 16"></path><path d="M19 9A7 7 0 0 0 7.1 5.1L4 8"></path></svg>',
    };

    function enableDesignMode() {
        const url = new URL(window.location.href);
        url.searchParams.set("design_mode", "1");
        window.location.href = url.toString();
    }

    function exitDesignMode() {
        const url = new URL(window.location.href);
        url.searchParams.delete("design_mode");
        window.location.href = url.toString();
    }

    function buildLauncher() {
        const button = document.createElement("button");
        button.className = "layout-adjust-launch";
        button.type = "button";
        button.innerHTML = `${icons.adjust}<span>Layout Adjust</span>`;
        button.addEventListener("click", enableDesignMode);
        document.body.appendChild(button);
    }

    if (!isEnabled) {
        buildLauncher();
        return;
    }

    function directSelector(componentKey) {
        return `[data-design-component="${componentKey.replace(/"/g, '\\"')}"]`;
    }

    function getSetting(settingKey) {
        if (!selectedComponent) return null;
        return (selectedComponent.settings || []).find((setting) => setting.key === settingKey) || null;
    }

    function findFirstSetting(settingKeys) {
        return settingKeys.map(getSetting).find(Boolean) || null;
    }

    function getTargetElement(setting) {
        if (!selectedElement) return null;
        const suffix = setting.selector_suffix || "";
        if (!suffix) return selectedElement;
        return selectedElement.querySelector(suffix.trim()) || selectedElement;
    }

    function cssValue(setting, value) {
        if (!value) return "";
        if (setting.key === "columns") return `repeat(${value}, minmax(0, 1fr))`;
        if (setting.key === "visibility") return value === "hidden" ? "none" : "";
        if (setting.key === "shadow") {
            if (value === "none") return "none";
            if (value === "soft") return "0 10px 24px rgba(15, 23, 42, .08)";
            if (value === "deep") return "0 18px 42px rgba(15, 23, 42, .16)";
            return "";
        }
        return value;
    }

    function fieldValueForSetting(setting, value) {
        if (setting.input_type === "number" && setting.unit && String(value || "").endsWith(setting.unit)) {
            return String(value).slice(0, -setting.unit.length);
        }
        return value || "";
    }

    function componentTypeForElement(element) {
        const tagName = element.tagName.toLowerCase();
        if (tagName === "button" || element.getAttribute("role") === "button" || element.className.includes("btn")) return "button";
        if (tagName === "table" || element.closest("table") === element) return "table";
        if (tagName === "nav" || element.className.includes("nav") || element.className.includes("sidebar")) return "navigation";
        if (["section", "article", "main", "aside", "header", "form"].includes(tagName)) return "section";
        return "element";
    }

    function labelForElement(element, index) {
        const tagName = element.tagName.toLowerCase();
        const text = (element.innerText || element.getAttribute("aria-label") || element.getAttribute("title") || "").trim().replace(/\s+/g, " ");
        if (text) return `${tagName}: ${text.slice(0, 42)}`;
        if (element.id) return `${tagName} #${element.id}`;
        return `${tagName} ${index + 1}`;
    }

    function buildCustomComponents() {
        const selectors = [
            ".page-stage section", ".page-stage article", ".page-stage .card", ".page-stage .stat",
            ".page-stage .workspace", ".page-stage .panel", ".page-stage table", ".page-stage form",
            ".page-stage button", ".page-stage a", ".page-stage input", ".page-stage select",
            ".page-stage h1", ".page-stage h2", ".page-stage h3", ".page-stage h4", ".page-stage p",
            ".app-header .header-chip", ".app-header img", ".app-sidebar .scope-pill", ".app-sidebar .sidebar-config-card",
        ].join(",");
        const candidates = Array.from(document.querySelectorAll(selectors));
        let index = 0;
        candidates.forEach((element) => {
            if (element.hasAttribute("data-design-component")) return;
            if (element.closest(".design-toolbar, .design-studio-panel")) return;
            const rect = element.getBoundingClientRect();
            if (rect.width < 12 || rect.height < 10) return;
            const key = `custom.${pageKey}.${index}`;
            index += 1;
            const componentType = componentTypeForElement(element);
            element.setAttribute("data-design-component", key);
            element.setAttribute("data-design-type", componentType);
            components.set(key, {
                key,
                label: labelForElement(element, index),
                page_key: pageKey,
                component_type: componentType,
                settings: universalSettings,
            });
        });
    }

    function collectSettings() {
        const values = {};
        document.querySelectorAll("[data-design-setting]").forEach((input) => {
            const key = input.getAttribute("data-design-setting");
            if (key) values[key] = input.value || "";
        });
        return values;
    }

    function setSettingValue(settingKey, value) {
        const input = document.querySelector(`[data-design-setting="${settingKey}"]`);
        if (!input) return;
        input.value = value;
        input.dispatchEvent(new Event("input", {bubbles: true}));
    }

    function applyPreview() {
        if (!selectedComponent) return;
        const values = collectSettings();
        selectedComponent.settings.forEach((setting) => {
            if (!setting.css_property) return;
            const target = getTargetElement(setting);
            if (!target) return;
            const rawValue = values[setting.key];
            const normalized = setting.input_type === "number" && rawValue && setting.unit ? `${rawValue}${setting.unit}` : rawValue;
            const value = cssValue(setting, normalized);
            if (value) {
                target.style.setProperty(setting.css_property, value);
            } else {
                target.style.removeProperty(setting.css_property);
            }
        });
        updateSizeReadout();
    }

    function setMessage(message, isError) {
        const messageEl = document.querySelector("[data-design-message]");
        if (!messageEl) return;
        messageEl.textContent = message || "";
        messageEl.style.color = isError ? "#9f2d1f" : "#027a48";
    }

    function clearResizeHandles() {
        document.querySelectorAll(".design-resize-handle, .design-size-readout").forEach((item) => item.remove());
    }

    function updateSizeReadout() {
        if (!selectedElement) return;
        const readout = selectedElement.querySelector(":scope > .design-size-readout");
        if (!readout) return;
        const rect = selectedElement.getBoundingClientRect();
        readout.textContent = `${Math.round(rect.width)} x ${Math.round(rect.height)}`;
    }

    function beginResize(event, mode) {
        if (!selectedElement || !selectedComponent) return;
        event.preventDefault();
        event.stopPropagation();
        const widthSetting = findFirstSetting(["width"]);
        const heightSetting = findFirstSetting(["min_height", "height"]);
        const startRect = selectedElement.getBoundingClientRect();
        const startX = event.clientX;
        const startY = event.clientY;

        function onMove(moveEvent) {
            if ((mode === "right" || mode === "corner") && widthSetting) {
                const nextWidth = Math.max(widthSetting.min_value || 40, Math.min(widthSetting.max_value || 1800, Math.round(startRect.width + moveEvent.clientX - startX)));
                selectedElement.style.width = `${nextWidth}px`;
                setSettingValue(widthSetting.key, String(nextWidth));
            }
            if ((mode === "bottom" || mode === "corner") && heightSetting) {
                const nextHeight = Math.max(heightSetting.min_value || 30, Math.min(heightSetting.max_value || 1400, Math.round(startRect.height + moveEvent.clientY - startY)));
                selectedElement.style.setProperty(heightSetting.css_property || "min-height", `${nextHeight}px`);
                setSettingValue(heightSetting.key, String(nextHeight));
            }
            updateSizeReadout();
        }

        function onUp() {
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        }

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    }

    function addResizeHandles() {
        clearResizeHandles();
        if (!selectedElement || !selectedComponent) return;
        const readout = document.createElement("span");
        readout.className = "design-size-readout";
        selectedElement.appendChild(readout);
        [
            ["right", "is-right"],
            ["bottom", "is-bottom"],
            ["corner", "is-corner"],
        ].forEach(([mode, className]) => {
            const handle = document.createElement("span");
            handle.className = `design-resize-handle ${className}`;
            handle.addEventListener("mousedown", (event) => beginResize(event, mode));
            selectedElement.appendChild(handle);
        });
        updateSizeReadout();
    }

    function renderFields() {
        const body = document.querySelector("[data-design-fields]");
        const title = document.querySelector("[data-design-title]");
        const meta = document.querySelector("[data-design-meta]");
        if (!body || !title || !meta) return;
        if (!selectedComponent) {
            title.textContent = "Layout Adjust";
            meta.textContent = "Select any highlighted component, then resize or format it.";
            body.innerHTML = '<p class="design-studio-empty">Choose a card, button, table, sidebar, or section to edit.</p>';
            return;
        }

        title.textContent = selectedComponent.label;
        meta.textContent = `${selectedComponent.component_type} | ${selectedComponent.key}`;
        const current = savedSettings[selectedComponent.key] || {};
        body.innerHTML = '<h3 class="design-studio-section-title">Properties</h3>';
        selectedComponent.settings.forEach((setting) => {
            const field = document.createElement("div");
            field.className = "design-studio-field";
            const label = document.createElement("label");
            label.textContent = setting.label;
            const input = setting.input_type === "select" ? document.createElement("select") : document.createElement("input");
            input.setAttribute("data-design-setting", setting.key);
            if (setting.input_type === "select") {
                (setting.options || []).forEach((option) => {
                    const optionEl = document.createElement("option");
                    optionEl.value = option;
                    optionEl.textContent = option;
                    input.appendChild(optionEl);
                });
            } else {
                input.type = setting.input_type === "color" ? "color" : "number";
                if (setting.min_value !== null && setting.min_value !== undefined) input.min = String(setting.min_value);
                if (setting.max_value !== null && setting.max_value !== undefined) input.max = String(setting.max_value);
            }
            let value = fieldValueForSetting(setting, current[setting.key] || setting.default || "");
            if (setting.input_type === "color" && !value) value = "#ffffff";
            input.value = value;
            input.addEventListener("input", applyPreview);
            input.addEventListener("change", applyPreview);
            field.appendChild(label);
            field.appendChild(input);
            body.appendChild(field);
        });
        applyPreview();
    }

    function selectComponent(element) {
        if (element.closest(".design-toolbar, .design-studio-panel")) return;
        if (selectedElement) selectedElement.classList.remove("is-design-selected");
        clearResizeHandles();
        selectedElement = element;
        selectedElement.classList.add("is-design-selected");
        selectedComponent = components.get(element.getAttribute("data-design-component"));
        renderFields();
        addResizeHandles();
        setMessage("");
    }

    async function saveSelected() {
        if (!selectedComponent) {
            setMessage("Select a component first.", true);
            return;
        }
        const response = await fetch("/api/design-studio/component-settings", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                page_key: selectedComponent.page_key || pageKey,
                component_key: selectedComponent.key,
                component_type: selectedComponent.component_type || "element",
                settings: collectSettings(),
            }),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
            setMessage(payload.error || "Unable to save design settings.", true);
            return;
        }
        savedSettings[selectedComponent.key] = payload.settings || {};
        setMessage("Saved.", false);
    }

    async function resetSelected() {
        if (!selectedComponent) {
            setMessage("Select a component first.", true);
            return;
        }
        const response = await fetch("/api/design-studio/reset", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({page_key: selectedComponent.page_key || pageKey, component_key: selectedComponent.key}),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
            setMessage(payload.error || "Unable to reset design settings.", true);
            return;
        }
        savedSettings[selectedComponent.key] = {};
        window.location.reload();
    }

    async function resetAllDesign() {
        const confirmed = window.confirm("Reset all design changes and return TIS to the original layout and theme?");
        if (!confirmed) return;
        const response = await fetch("/api/design-studio/reset-all", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({}),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
            setMessage(payload.error || "Unable to reset all design settings.", true);
            return;
        }
        window.location.href = window.location.pathname;
    }

    function applyToolbarValue(settingKeys, value) {
        const setting = findFirstSetting(settingKeys);
        if (!setting) {
            setMessage("This action is not available for the selected component.", true);
            return;
        }
        setSettingValue(setting.key, value);
        setMessage("");
    }

    function buildToolbar() {
        const toolbar = document.createElement("div");
        toolbar.className = "design-toolbar";
        toolbar.innerHTML = `
            <div class="design-toolbar-group">
                <button class="design-tool-btn is-primary" type="button" title="Select component">${icons.select}<span>Select</span></button>
                <button class="design-tool-btn" type="button" title="Drag blue handles to resize">${icons.resize}<span>Resize</span></button>
            </div>
            <div class="design-toolbar-group">
                <input class="design-tool-swatch" type="color" value="#ffffff" title="Background color" data-toolbar-color>
                <button class="design-tool-btn" type="button" data-toolbar-shadow="soft" title="Soft shadow">Shadow</button>
                <button class="design-tool-btn" type="button" data-toolbar-hide title="Toggle visibility">${icons.hide}</button>
            </div>
            <div class="design-toolbar-group">
                <button class="design-tool-btn" type="button" data-toolbar-align="left" title="Align left">${icons.alignLeft}</button>
                <button class="design-tool-btn" type="button" data-toolbar-align="center" title="Align center">${icons.alignCenter}</button>
                <button class="design-tool-btn" type="button" data-toolbar-align="right" title="Align right">${icons.alignRight}</button>
            </div>
            <div class="design-toolbar-group">
                <button class="design-tool-btn is-primary" type="button" data-design-save>${icons.save}<span>Save</span></button>
                <button class="design-tool-btn is-danger" type="button" data-design-reset>${icons.reset}<span>Reset</span></button>
                <button class="design-tool-btn is-danger" type="button" data-design-reset-all>${icons.resetAll}<span>Reset All</span></button>
                <button class="design-tool-btn" type="button" data-design-exit>${icons.close}<span>Exit</span></button>
            </div>
        `;
        document.body.appendChild(toolbar);
        toolbar.querySelector("[data-design-save]").addEventListener("click", saveSelected);
        toolbar.querySelector("[data-design-reset]").addEventListener("click", resetSelected);
        toolbar.querySelector("[data-design-reset-all]").addEventListener("click", resetAllDesign);
        toolbar.querySelector("[data-design-exit]").addEventListener("click", exitDesignMode);
        toolbar.querySelector("[data-toolbar-color]").addEventListener("input", (event) => {
            applyToolbarValue(["background", "active_background", "border_color", "header_background"], event.target.value);
        });
        toolbar.querySelector("[data-toolbar-shadow]").addEventListener("click", () => applyToolbarValue(["shadow"], "soft"));
        toolbar.querySelector("[data-toolbar-hide]").addEventListener("click", () => {
            const visibility = document.querySelector('[data-design-setting="visibility"]');
            applyToolbarValue(["visibility"], visibility && visibility.value === "hidden" ? "visible" : "hidden");
        });
        toolbar.querySelectorAll("[data-toolbar-align]").forEach((button) => {
            button.addEventListener("click", () => applyToolbarValue(["alignment"], button.getAttribute("data-toolbar-align")));
        });
    }

    function buildPanel() {
        const panel = document.createElement("aside");
        panel.className = "design-studio-panel";
        panel.innerHTML = `
            <div class="design-studio-head">
                <h2 data-design-title>Layout Adjust</h2>
                <p data-design-meta>Select any highlighted component, then resize or format it.</p>
                <p class="design-studio-message" data-design-message></p>
            </div>
            <div class="design-studio-summary">Manual resize: drag the blue handles on the selected component. All supported width and height changes are saved from this panel.</div>
            <div class="design-studio-body" data-design-fields>
                <p class="design-studio-empty">Choose a component to edit.</p>
            </div>
            <div class="design-studio-actions">
                <button class="design-studio-btn is-primary" type="button" data-design-save>${icons.save} Save</button>
                <button class="design-studio-btn is-danger" type="button" data-design-reset>${icons.reset} Reset</button>
                <button class="design-studio-btn is-danger" type="button" data-design-reset-all>${icons.resetAll} Reset All</button>
                <button class="design-studio-btn" type="button" data-design-exit>${icons.close} Exit</button>
            </div>
        `;
        document.body.appendChild(panel);
        panel.querySelector("[data-design-save]").addEventListener("click", saveSelected);
        panel.querySelector("[data-design-reset]").addEventListener("click", resetSelected);
        panel.querySelector("[data-design-reset-all]").addEventListener("click", resetAllDesign);
        panel.querySelector("[data-design-exit]").addEventListener("click", exitDesignMode);
    }

    function bindComponents() {
        components.forEach((component) => {
            document.querySelectorAll(directSelector(component.key)).forEach((element) => {
                element.setAttribute("data-design-label", component.label);
                element.setAttribute("title", `Layout Adjust: ${component.label}`);
            });
        });
        document.addEventListener("click", (event) => {
            if (event.target.closest(".design-toolbar, .design-studio-panel, .design-resize-handle")) return;
            const element = event.target.closest("[data-design-component]");
            if (!element || !components.has(element.getAttribute("data-design-component"))) return;
            event.preventDefault();
            event.stopPropagation();
            selectComponent(element);
        }, true);
    }

    buildToolbar();
    buildPanel();
    buildCustomComponents();
    bindComponents();
})();
