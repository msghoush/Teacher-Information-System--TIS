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

    const setGradeState = (gradeSelect, { loading = false, grades = null } = {}) => {
        gradeSelect.replaceChildren();
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = loading ? "Loading configured Grades…" :
            (grades && grades.length === 0 ? "No configured Grades" : "Select grade");
        gradeSelect.appendChild(placeholder);
        (grades || []).forEach((grade) => {
            const option = document.createElement("option");
            option.value = String(grade);
            option.textContent = grade === "KG" ? "KG" : `Grade ${grade}`;
            gradeSelect.appendChild(option);
        });
        gradeSelect.disabled = loading || !grades || grades.length === 0;
    };

    const setSectionState = (sectionSelect, hint, submitButton, { loading = false, items = null, error = false } = {}) => {
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
            placeholder.textContent = error ? "Sections could not be loaded" : "No Sections available";
            sectionSelect.appendChild(placeholder);
            sectionSelect.disabled = true;
            sectionSelect.required = false;
            if (hint) {
                hint.hidden = false;
                hint.textContent = error ? "Sections could not be loaded. Check your connection and try changing the selection again." : NO_SECTIONS_TEXT;
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

        const refreshSections = async () => {
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
                    setSectionState(sectionSelect, hint, submitButton, { items: [], error: true });
                    return;
                }
                const payload = await response.json();
                setSectionState(sectionSelect, hint, submitButton, { items: payload.items || [] });
            } catch (error) {
                if (version === requestVersion) {
                    setSectionState(sectionSelect, hint, submitButton, { items: [], error: true });
                }
            }
        };

        const refreshGrades = async () => {
            const academicYearId = yearSelect.value;
            const branchId = branchSelect.value;
            setSectionState(sectionSelect, hint, submitButton, {});
            if (!academicYearId || !branchId) {
                setGradeState(gradeSelect, {});
                return;
            }
            const version = ++requestVersion;
            setGradeState(gradeSelect, { loading: true });
            if (submitButton) submitButton.disabled = true;
            try {
                const url = `${apiBase}?branch_id=${encodeURIComponent(branchId)}&academic_year_id=${encodeURIComponent(academicYearId)}`;
                const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
                if (version !== requestVersion) return;
                if (!response.ok) {
                    setGradeState(gradeSelect, { grades: [] });
                    setSectionState(sectionSelect, hint, submitButton, { items: [], error: true });
                    return;
                }
                const payload = await response.json();
                setGradeState(gradeSelect, { grades: payload.grades || [] });
                if (!payload.grades || payload.grades.length === 0) {
                    setSectionState(sectionSelect, hint, submitButton, { items: [] });
                }
            } catch (error) {
                if (version === requestVersion) {
                    setGradeState(gradeSelect, { grades: [] });
                    setSectionState(sectionSelect, hint, submitButton, { items: [], error: true });
                }
            }
        };

        [yearSelect, branchSelect].forEach((select) => select.addEventListener("change", refreshGrades));
        gradeSelect.addEventListener("change", refreshSections);
        form.addEventListener("submit", async (event) => {
            if (!form.checkValidity() || !sectionSelect.value) {
                event.preventDefault();
                form.reportValidity();
                if (hint) {
                    hint.hidden = false;
                    hint.textContent = "Choose a configured Section before saving.";
                }
                return;
            }
            if (form.dataset.openCyclePreview && form.dataset.openCycleConfirmed !== "true") {
                event.preventDefault();
                const preview = new URL(form.dataset.openCyclePreview, window.location.origin);
                preview.searchParams.set("academic_year_id", yearSelect.value);
                preview.searchParams.set("branch_id", branchSelect.value);
                preview.searchParams.set("planning_section_id", sectionSelect.value);
                preview.searchParams.set("student_id", form.dataset.studentId);
                try {
                    const response = await fetch(preview, {
                        credentials: "same-origin",
                        headers: { Accept: "application/json" },
                    });
                    if (!response.ok) throw new Error("preview_failed");
                    const payload = await response.json();
                    if (Number(payload.open_cycle_count || 0) > 0) {
                        const confirmed = window.confirm(
                            "Student will be added to an open assessment.\n\n" +
                            "This placement makes the Student eligible for an already-open Talent assessment cycle.\n" +
                            "After saving, the Student will be added as Not Started.\n" +
                            "Existing assessment records will not be changed."
                        );
                        if (!confirmed) return;
                    }
                    form.dataset.openCycleConfirmed = "true";
                    form.requestSubmit(submitButton);
                } catch (_) {
                    if (hint) {
                        hint.hidden = false;
                        hint.textContent = "Open-assessment eligibility could not be checked. Please try saving again.";
                    }
                }
                return;
            }
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.setAttribute("aria-busy", "true");
                submitButton.textContent = "Saving placement…";
            }
        });
        refreshGrades();
    };

    document.querySelectorAll("[data-stu-cascade-group]").forEach((form) => {
        initializeCascadeGroup(form);
    });

    document.querySelectorAll("[data-rubric-level]").forEach((target) => {
        try {
            const level = JSON.parse(target.dataset.rubricLevel || "null");
            if (level && window.TalentRubricVisual) {
                target.outerHTML = window.TalentRubricVisual.badge(level);
            }
        } catch (_) {
            // Keep the server-rendered label as an accessible fallback.
        }
    });

    document.querySelectorAll("[data-ls-filter-cascade]").forEach((form) => {
        const branch = form.querySelector('[name="branch_id"]');
        const grade = form.querySelector('[name="grade"]');
        const section = form.querySelector('[name="section"]');
        if (!branch || !grade || !section) return;
        branch.addEventListener("change", () => {
            grade.value = "";
            section.value = "";
            form.requestSubmit();
        });
        grade.addEventListener("change", () => {
            section.value = "";
            form.requestSubmit();
        });
        section.addEventListener("change", () => form.requestSubmit());
    });
})();
