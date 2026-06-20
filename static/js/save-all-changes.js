(() => {
    "use strict";

    const ignoredFieldNames = new Set(["return_to"]);

    const formForRow = (row) => {
        const formId = row.dataset.saveAllFormId;
        if (formId) {
            return document.getElementById(formId);
        }
        if (row.matches("form[data-save-all-form]")) {
            return row;
        }
        return row.querySelector("form[data-save-all-form]");
    };

    const serializeForm = (form) => {
        const values = {};
        if (!form) {
            return values;
        }
        Array.from(form.elements).forEach((control) => {
            const name = control.name;
            if (
                !name
                || ignoredFieldNames.has(name)
                || control.disabled
                || control.type === "submit"
                || control.type === "button"
                || control.type === "file"
            ) {
                return;
            }
            if (control.type === "radio") {
                if (control.checked) {
                    values[name] = control.value;
                }
                return;
            }
            if (control.type === "checkbox") {
                values[name] = Boolean(control.checked);
                return;
            }
            values[name] = control.value;
        });
        return values;
    };

    const changedFieldNames = (initialValues, currentValues) => {
        const names = new Set([
            ...Object.keys(initialValues || {}),
            ...Object.keys(currentValues || {}),
        ]);
        return Array.from(names).filter(
            (name) => JSON.stringify(initialValues[name]) !== JSON.stringify(currentValues[name])
        );
    };

    const initializeSaveAll = (container) => {
        const endpoint = container.dataset.saveAllEndpoint;
        const rows = Array.from(container.querySelectorAll("[data-save-all-row]"));
        const submitButton = container.querySelector("[data-save-all-submit]");
        const countNode = container.querySelector("[data-save-all-count]");
        const feedback = container.querySelector("[data-save-all-feedback]");
        if (!endpoint || !rows.length || !submitButton) {
            return;
        }

        const initialValues = new Map();
        let isSaving = false;
        let isIntentionalNavigation = false;

        const setFeedback = (message = "", state = "") => {
            if (!feedback) {
                return;
            }
            feedback.textContent = message;
            feedback.dataset.state = state;
            feedback.hidden = !message;
        };

        const rowErrorNode = (row) => row.querySelector("[data-save-all-row-error]");

        const clearRowError = (row) => {
            row.classList.remove("has-save-all-error");
            const errorNode = rowErrorNode(row);
            if (errorNode) {
                errorNode.textContent = "";
                errorNode.hidden = true;
            }
        };

        const showRowError = (row, message) => {
            row.classList.add("has-save-all-error");
            const errorNode = rowErrorNode(row);
            if (errorNode) {
                errorNode.textContent = message;
                errorNode.hidden = false;
            }
        };

        const dirtyRows = () => rows.filter((row) => row.classList.contains("is-save-all-dirty"));

        const updateToolbar = () => {
            const count = dirtyRows().length;
            if (countNode) {
                countNode.textContent = String(count);
            }
            submitButton.disabled = isSaving || count === 0;
            submitButton.setAttribute(
                "aria-label",
                count ? `Save all ${count} modified item${count === 1 ? "" : "s"}` : "No modified items to save"
            );
        };

        const refreshRow = (row) => {
            const form = formForRow(row);
            const initial = initialValues.get(row);
            if (!form || !initial) {
                return;
            }
            const current = serializeForm(form);
            const changed = changedFieldNames(initial, current);
            row.classList.toggle("is-save-all-dirty", changed.length > 0);
            row.dataset.saveAllChangedFields = JSON.stringify(changed);
            clearRowError(row);
            setFeedback();
            updateToolbar();
        };

        const refreshLocationSnapshot = (row, locationFields) => {
            const form = formForRow(row);
            const initial = { ...(initialValues.get(row) || {}) };
            const current = serializeForm(form);
            const locationNames = new Set(
                Array.from(
                    locationFields.querySelectorAll(
                        "[data-location-country], [data-location-region], [data-location-region-manual], [data-location-city], [data-location-city-manual]"
                    )
                ).map((control) => control.name)
            );
            locationNames.forEach((name) => {
                if (Object.prototype.hasOwnProperty.call(current, name)) {
                    initial[name] = current[name];
                } else {
                    delete initial[name];
                }
            });
            initialValues.set(row, initial);
            refreshRow(row);
        };

        rows.forEach((row) => {
            const form = formForRow(row);
            if (!form) {
                return;
            }
            initialValues.set(row, serializeForm(form));
            row.dataset.saveAllChangedFields = "[]";
            row.addEventListener("input", () => refreshRow(row));
            row.addEventListener("change", () => refreshRow(row));
            row.querySelectorAll("[data-location-fields]").forEach((locationFields) => {
                if (locationFields.dataset.locationReady === "true") {
                    refreshLocationSnapshot(row, locationFields);
                } else {
                    locationFields.addEventListener(
                        "tis:location-ready",
                        () => refreshLocationSnapshot(row, locationFields),
                        { once: true }
                    );
                }
            });
        });

        const applyErrors = (errors) => {
            const messages = [];
            let firstErrorRow = null;
            (errors || []).forEach((error) => {
                const itemId = String(error.id ?? "");
                const row = rows.find((candidate) => candidate.dataset.saveAllId === itemId);
                const label = error.label || "Record";
                const message = error.message || "Unable to save this record.";
                messages.push(`${label}: ${message}`);
                if (row) {
                    showRowError(row, message);
                    firstErrorRow = firstErrorRow || row;
                }
            });
            setFeedback(messages.join(" ") || "Unable to save the modified items.", "error");
            if (firstErrorRow) {
                firstErrorRow.scrollIntoView({ block: "center", behavior: "smooth" });
            }
        };

        submitButton.addEventListener("click", async () => {
            const modifiedRows = dirtyRows();
            if (!modifiedRows.length || isSaving) {
                return;
            }

            let firstInvalidForm = null;
            modifiedRows.forEach((row) => {
                const form = formForRow(row);
                if (form && !form.checkValidity()) {
                    showRowError(row, "Complete the highlighted required or invalid fields.");
                    firstInvalidForm = firstInvalidForm || form;
                }
            });
            if (firstInvalidForm) {
                setFeedback("Fix the highlighted items before saving.", "error");
                firstInvalidForm.reportValidity();
                return;
            }

            const items = modifiedRows.map((row) => {
                const form = formForRow(row);
                const current = serializeForm(form);
                const changed = changedFieldNames(initialValues.get(row) || {}, current);
                return {
                    id: row.dataset.saveAllId,
                    ...current,
                    _changed_fields: changed,
                };
            });

            isSaving = true;
            submitButton.classList.add("is-saving");
            updateToolbar();
            setFeedback(`Saving ${items.length} modified item${items.length === 1 ? "" : "s"}...`, "pending");
            modifiedRows.forEach(clearRowError);

            try {
                const response = await fetch(endpoint, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        Accept: "application/json",
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ items }),
                });
                const contentType = response.headers.get("content-type") || "";
                if (!contentType.includes("application/json")) {
                    throw new Error("The session or page state changed. Refresh and try again.");
                }
                const result = await response.json();
                if (!response.ok || !result.ok) {
                    applyErrors(result.errors);
                    return;
                }

                modifiedRows.forEach((row) => {
                    const form = formForRow(row);
                    initialValues.set(row, serializeForm(form));
                    row.classList.remove("is-save-all-dirty");
                    row.dataset.saveAllChangedFields = "[]";
                    Array.from(form.elements).forEach((control) => {
                        if (control.hasAttribute("data-initial")) {
                            control.setAttribute("data-initial", control.value);
                        }
                    });
                });
                setFeedback(result.message || "All modified items were saved.", "success");
                container.dispatchEvent(
                    new CustomEvent("tis:save-all-success", {
                        bubbles: true,
                        detail: { rows: modifiedRows, result },
                    })
                );
            } catch (error) {
                setFeedback(error.message || "Unable to save the modified items.", "error");
            } finally {
                isSaving = false;
                submitButton.classList.remove("is-saving");
                updateToolbar();
            }
        });

        container.addEventListener("submit", () => {
            isIntentionalNavigation = true;
        });

        window.addEventListener("beforeunload", (event) => {
            if (!dirtyRows().length || isSaving || isIntentionalNavigation) {
                return;
            }
            event.preventDefault();
            event.returnValue = "";
        });

        updateToolbar();
    };

    document.querySelectorAll("[data-save-all-container]").forEach(initializeSaveAll);
})();
