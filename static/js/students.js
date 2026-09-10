(() => {
    "use strict";

    /**
     * Real, live Academic Placement Section cascade for the Students UI.
     *
     * Selecting Academic Year + Branch + Grade fetches the actual configured
     * PlanningSection rows for that exact combination from the server
     * (GET /students/sections, backed by Planning's own canonical
     * list_operational_planning_sections authority - never fabricated
     * client-side data). When no Sections exist for the combination, the
     * Section control is disabled with an explanatory message instead of
     * falling back to free-text entry.
     */

    const NO_SECTIONS_TEXT = "No Sections configured for this Grade.";
    const SELECT_FIRST_TEXT = "Select academic year, branch, and grade first";
    const LOADING_TEXT = "Loading sections…";

    const setSectionState = (sectionSelect, hint, submitButton, { loading = false, items = null } = {}) => {
        sectionSelect.replaceChildren();
        const placeholder = document.createElement("option");
        placeholder.value = "";

        if (loading) {
            placeholder.textContent = LOADING_TEXT;
            sectionSelect.appendChild(placeholder);
            sectionSelect.disabled = true;
            sectionSelect.required = false;
            if (hint) hint.hidden = true;
            if (submitButton) submitButton.disabled = true;
            return;
        }

        if (!items) {
            placeholder.textContent = SELECT_FIRST_TEXT;
            sectionSelect.appendChild(placeholder);
            sectionSelect.disabled = true;
            sectionSelect.required = false;
            if (hint) hint.hidden = true;
            if (submitButton) submitButton.disabled = false;
            return;
        }

        if (items.length === 0) {
            placeholder.textContent = "No Sections available";
            sectionSelect.appendChild(placeholder);
            sectionSelect.disabled = true;
            sectionSelect.required = false;
            if (hint) {
                hint.hidden = false;
                hint.textContent = NO_SECTIONS_TEXT;
            }
            if (submitButton) submitButton.disabled = true;
            return;
        }

        placeholder.textContent = "Select a section";
        sectionSelect.appendChild(placeholder);
        items.forEach((item) => {
            const option = document.createElement("option");
            option.value = String(item.id);
            option.textContent = item.section_name;
            sectionSelect.appendChild(option);
        });
        sectionSelect.disabled = false;
        sectionSelect.required = true;
        if (hint) hint.hidden = true;
        if (submitButton) submitButton.disabled = false;
    };

    const initializeCascadeGroup = (form) => {
        const yearSelect = form.querySelector('[data-stu-cascade="year"]');
        const branchSelect = form.querySelector('[data-stu-cascade="branch"]');
        const gradeSelect = form.querySelector('[data-stu-cascade="grade"]');
        const sectionSelect = form.querySelector('[data-stu-cascade="section"]');
        const hint = form.querySelector('[data-stu-cascade="section-hint"]');
        const submitButton = form.querySelector('[data-stu-cascade="submit"]');
        const apiBase = form.dataset.sectionsApi || "/students/sections";
        if (!yearSelect || !branchSelect || !gradeSelect || !sectionSelect) {
            return;
        }

        let requestVersion = 0;

        const refresh = async () => {
            const academicYearId = yearSelect.value;
            const branchId = branchSelect.value;
            const gradeLevel = gradeSelect.value;
            if (!academicYearId || !branchId || !gradeLevel) {
                setSectionState(sectionSelect, hint, submitButton, {});
                return;
            }
            const version = ++requestVersion;
            setSectionState(sectionSelect, hint, submitButton, { loading: true });
            try {
                const url = `${apiBase}?branch_id=${encodeURIComponent(branchId)}&academic_year_id=${encodeURIComponent(academicYearId)}&grade_level=${encodeURIComponent(gradeLevel)}`;
                const response = await fetch(url, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                if (version !== requestVersion) {
                    return;
                }
                if (!response.ok) {
                    setSectionState(sectionSelect, hint, submitButton, { items: [] });
                    return;
                }
                const payload = await response.json();
                setSectionState(sectionSelect, hint, submitButton, { items: payload.items || [] });
            } catch (error) {
                if (version === requestVersion) {
                    setSectionState(sectionSelect, hint, submitButton, { items: [] });
                }
            }
        };

        [yearSelect, branchSelect, gradeSelect].forEach((select) => {
            select.addEventListener("change", refresh);
        });
        setSectionState(sectionSelect, hint, submitButton, {});
    };

    document.querySelectorAll("[data-stu-cascade-group]").forEach((form) => {
        initializeCascadeGroup(form);
    });
})();
