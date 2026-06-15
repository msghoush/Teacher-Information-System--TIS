(function () {
    const configEl = document.getElementById("tis-design-studio-config");
    if (!configEl) {
        return;
    }

    let config = {};
    try {
        config = JSON.parse(configEl.textContent || "{}");
    } catch (error) {
        config = {};
    }

    const components = new Map((config.components || []).map((component) => [component.key, component]));
    const savedSettings = config.saved_settings || {};
    let selectedElement = null;
    let selectedComponent = null;

    function directSelector(componentKey) {
        return `[data-design-component="${componentKey.replace(/"/g, '\\"')}"]`;
    }

    function getTargetElement(setting) {
        if (!selectedElement) {
            return null;
        }
        const suffix = setting.selector_suffix || "";
        if (!suffix) {
            return selectedElement;
        }
        return selectedElement.querySelector(suffix.trim()) || selectedElement;
    }

    function cssValue(setting, value) {
        if (!value) {
            return "";
        }
        if (setting.key === "columns") {
            return `repeat(${value}, minmax(0, 1fr))`;
        }
        if (setting.key === "visibility") {
            return value === "hidden" ? "none" : "";
        }
        if (setting.key === "shadow") {
            if (value === "none") return "none";
            if (value === "soft") return "0 10px 24px rgba(15, 23, 42, .08)";
            if (value === "deep") return "0 18px 42px rgba(15, 23, 42, .16)";
            return "";
        }
        return value;
    }

    function collectSettings() {
        const values = {};
        document.querySelectorAll("[data-design-setting]").forEach((input) => {
            const key = input.getAttribute("data-design-setting");
            if (!key) return;
            values[key] = input.value || "";
        });
        return values;
    }

    function applyPreview() {
        if (!selectedComponent) {
            return;
        }
        const values = collectSettings();
        selectedComponent.settings.forEach((setting) => {
            if (!setting.css_property) {
                return;
            }
            const target = getTargetElement(setting);
            if (!target) {
                return;
            }
            const value = cssValue(setting, values[setting.key]);
            if (value) {
                target.style.setProperty(setting.css_property, value);
            } else {
                target.style.removeProperty(setting.css_property);
            }
        });
    }

    function setMessage(message, isError) {
        const messageEl = document.querySelector("[data-design-message]");
        if (!messageEl) {
            return;
        }
        messageEl.textContent = message || "";
        messageEl.style.color = isError ? "#9f2d1f" : "#027a48";
    }

    function renderFields() {
        const body = document.querySelector("[data-design-fields]");
        const title = document.querySelector("[data-design-title]");
        const meta = document.querySelector("[data-design-meta]");
        if (!body || !title || !meta) {
            return;
        }
        if (!selectedComponent) {
            title.textContent = "Design Studio";
            meta.textContent = "Select a highlighted component on the page.";
            body.innerHTML = '<p class="design-studio-empty">No component selected.</p>';
            return;
        }

        title.textContent = selectedComponent.label;
        meta.textContent = `${selectedComponent.component_type} | ${selectedComponent.key}`;
        const current = savedSettings[selectedComponent.key] || {};
        body.innerHTML = "";
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
            let value = current[setting.key] || setting.default || "";
            if (setting.input_type === "number" && setting.unit && value.endsWith(setting.unit)) {
                value = value.slice(0, -setting.unit.length);
            }
            if (setting.input_type === "color" && !value) {
                value = "#ffffff";
            }
            input.value = value;
            input.addEventListener("input", applyPreview);
            input.addEventListener("change", applyPreview);
            field.appendChild(label);
            field.appendChild(input);
            body.appendChild(field);
        });
    }

    function selectComponent(element) {
        if (selectedElement) {
            selectedElement.classList.remove("is-design-selected");
        }
        selectedElement = element;
        selectedElement.classList.add("is-design-selected");
        selectedComponent = components.get(element.getAttribute("data-design-component"));
        renderFields();
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
                component_key: selectedComponent.key,
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
            body: JSON.stringify({component_key: selectedComponent.key}),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
            setMessage(payload.error || "Unable to reset design settings.", true);
            return;
        }
        savedSettings[selectedComponent.key] = {};
        window.location.reload();
    }

    function exitDesignMode() {
        const url = new URL(window.location.href);
        url.searchParams.delete("design_mode");
        window.location.href = url.toString();
    }

    function buildPanel() {
        const panel = document.createElement("aside");
        panel.className = "design-studio-panel";
        panel.innerHTML = `
            <div class="design-studio-head">
                <h2 data-design-title>Design Studio</h2>
                <p data-design-meta>Select a highlighted component on the page.</p>
                <p class="design-studio-message" data-design-message></p>
            </div>
            <div class="design-studio-body" data-design-fields>
                <p class="design-studio-empty">No component selected.</p>
            </div>
            <div class="design-studio-actions">
                <button class="design-studio-btn is-primary" type="button" data-design-save>Save</button>
                <button class="design-studio-btn is-danger" type="button" data-design-reset>Reset</button>
                <button class="design-studio-btn" type="button" data-design-exit>Exit</button>
            </div>
        `;
        document.body.appendChild(panel);
        panel.querySelector("[data-design-save]").addEventListener("click", saveSelected);
        panel.querySelector("[data-design-reset]").addEventListener("click", resetSelected);
        panel.querySelector("[data-design-exit]").addEventListener("click", exitDesignMode);
    }

    function bindComponents() {
        components.forEach((component) => {
            document.querySelectorAll(directSelector(component.key)).forEach((element) => {
                element.setAttribute("data-design-label", component.label);
            });
        });
        document.addEventListener("click", (event) => {
            const element = event.target.closest("[data-design-component]");
            if (!element || !components.has(element.getAttribute("data-design-component"))) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            selectComponent(element);
        }, true);
    }

    buildPanel();
    bindComponents();
})();
