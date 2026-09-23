(() => {
  "use strict";

  const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const isXlsx = file => Boolean(file && /\.xlsx$/i.test(file.name || ""));
  const displayStudentId = value => value == null || value === "" ? "—" : (/^STD\d{10}$/.test(String(value)) ? String(value) : `STD${String(value)}`);
  const safeFilename = header => {
    const match = String(header || "").match(/filename\*?=(?:UTF-8''|\")?([^";]+)/i);
    if (!match) return "student_roster_export.xlsx";
    try { return decodeURIComponent(match[1].trim()); } catch (_) { return "student_roster_export.xlsx"; }
  };
  const resultMessage = row => {
    if (row?.status === "ok") return "Valid — ready to create";
    if (row?.status === "no_change") return "No change — matches existing record";
    return (row?.errors || []).map(error => {
      const field = error.field ? `${String(error.field).replaceAll("_", " ")}: ` : "";
      const identity = error.display_name ? ` (${error.display_name})` : "";
      return `${field}${error.safe_message || "This row is invalid."}${identity}`;
    }).join("; ") || "This row is invalid.";
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { isXlsx, displayStudentId, safeFilename, resultMessage };
    return;
  }

  const dialog = document.querySelector("[data-roster-dialog]");
  const openButton = document.querySelector("[data-roster-import-open]");
  const exportButton = document.querySelector("[data-roster-export]");
  const fileInput = document.querySelector("[data-roster-file]");
  const filename = document.querySelector("[data-roster-filename]");
  const previewButton = document.querySelector("[data-roster-preview]");
  const clearButton = document.querySelector("[data-roster-clear]");
  const status = document.querySelector("[data-roster-status]");
  const results = document.querySelector("[data-roster-results]");
  const summary = document.querySelector("[data-roster-summary]");
  const rowsTarget = document.querySelector("[data-roster-rows]");
  const applyArea = document.querySelector("[data-roster-apply-area]");
  const applyButton = document.querySelector("[data-roster-apply]");
  let selectedFile = null;
  let busy = false;

  const announce = (message, error = false) => {
    if (!status) return;
    status.textContent = message;
    status.className = `stu-banner ${error ? "stu-banner-error" : ""}`;
    status.focus();
  };
  const setBusy = (value, label) => {
    busy = value;
    [previewButton, applyButton, clearButton].forEach(button => { if (button) button.disabled = value || (!selectedFile && button !== clearButton); });
    if (previewButton) { previewButton.setAttribute("aria-busy", String(value)); previewButton.textContent = value && label === "preview" ? "Validating…" : "Preview and validate"; }
    if (applyButton) { applyButton.setAttribute("aria-busy", String(value)); applyButton.textContent = value && label === "apply" ? "Applying…" : "Confirm and apply import"; }
  };
  const resetPreview = () => {
    if (results) results.hidden = true;
    if (applyArea) applyArea.hidden = true;
    if (rowsTarget) rowsTarget.replaceChildren();
  };
  const clearSelection = () => {
    selectedFile = null;
    if (fileInput) fileInput.value = "";
    if (filename) filename.textContent = "No workbook selected.";
    resetPreview();
    setBusy(false);
    announce("Choose a workbook to begin.");
  };
  const cell = (row, text, heading = false) => {
    const node = document.createElement(heading ? "th" : "td");
    if (heading) node.scope = "row";
    node.textContent = text == null || text === "" ? "—" : String(text);
    row.appendChild(node);
  };
  const renderPreview = payload => {
    const counts = payload.summary || {};
    const parts = [`${Number(counts.total_rows || 0)} total`];
    if (Number(counts.valid_rows || 0) > 0) parts.push(`${Number(counts.valid_rows || 0)} to create`);
    if (Number(counts.no_change_rows || 0) > 0) parts.push(`${Number(counts.no_change_rows || 0)} no change`);
    parts.push(`${Number(counts.error_rows || 0)} with problems`);
    summary.textContent = parts.join(" · ");
    rowsTarget.replaceChildren();
    (payload.rows || []).forEach(item => {
      const tr = document.createElement("tr");
      tr.className = item.status === "ok" ? "" : (item.status === "no_change" ? "stu-roster-row-nochange" : "stu-roster-row-error");
      const data = item.data || {};
      cell(tr, item.row, true);
      cell(tr, displayStudentId(data.student_number));
      cell(tr, [data.first_name, data.father_name, data.last_name].filter(Boolean).join(" "));
      cell(tr, data.branch_name);
      cell(tr, data.grade_level && data.section_name ? `Grade ${data.grade_level} · ${data.section_name}` : "—");
      cell(tr, data.academic_year_name);
      cell(tr, resultMessage(item));
      rowsTarget.appendChild(tr);
    });
    results.hidden = false;
    applyArea.hidden = Number(counts.valid_rows || 0) === 0 || Number(counts.error_rows || 0) > 0;
  };
  const upload = async path => {
    const body = new FormData();
    body.append("roster_file", selectedFile, selectedFile.name);
    const response = await fetch(path, { method: "POST", credentials: "same-origin", headers: { Accept: "application/json" }, body });
    let payload;
    try { payload = await response.json(); } catch (_) { payload = {}; }
    return { response, payload };
  };

  openButton?.addEventListener("click", () => { dialog.showModal(); fileInput?.focus(); });
  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0] || null;
    resetPreview();
    if (!file) return clearSelection();
    if (!isXlsx(file)) {
      fileInput.value = "";
      selectedFile = null;
      filename.textContent = "No workbook selected.";
      setBusy(false);
      announce("Choose an .xlsx workbook. CSV and .xls files are not supported.", true);
      return;
    }
    selectedFile = file;
    filename.textContent = file.name;
    setBusy(false);
    announce("Workbook selected. Preview and validate it before applying.");
  });
  clearButton?.addEventListener("click", clearSelection);
  previewButton?.addEventListener("click", async () => {
    if (!selectedFile || busy) return;
    setBusy(true, "preview");
    resetPreview();
    try {
      const { response, payload } = await upload("/api/students/roster/import/preview");
      if (payload.file_error) {
        announce(payload.file_error.safe_message || "The workbook could not be validated.", true);
      } else {
        renderPreview(payload);
        const errors = Number(payload.summary?.error_rows || 0);
        announce(response.ok && errors === 0 ? "Preview complete. Review the rows, then confirm the import." : "Preview found problems. Fix the workbook and preview it again.", !response.ok || errors > 0);
      }
    } catch (_) { announce("The workbook could not be validated. Check your connection and try again.", true); }
    finally { setBusy(false); }
  });
  applyButton?.addEventListener("click", async () => {
    if (!selectedFile || busy || !window.confirm("Create the new Students in this workbook? The server will validate it again. Unchanged rows are skipped; if any row fails, no Student will be created.")) return;
    setBusy(true, "apply");
    try {
      const { response, payload } = await upload("/api/students/roster/import/apply");
      if (response.ok && payload.applied === true) {
        const created = Array.isArray(payload.created_student_ids) ? payload.created_student_ids.length : Number(payload.summary?.valid_rows || 0);
        const skipped = Number(payload.summary?.no_change_rows || 0);
        announce(`${created} Student${created === 1 ? "" : "s"} created successfully.${skipped > 0 ? ` ${skipped} unchanged row${skipped === 1 ? "" : "s"} skipped.` : ""}`);
        selectedFile = null;
        fileInput.value = "";
        resetPreview();
        window.location.assign(`/students/?success=roster-imported-${created}`);
        return;
      }
      if (payload.rows?.length) renderPreview(payload);
      announce(payload.file_error?.safe_message || "The import was rejected. No Students were created. Review the workbook and try again.", true);
    } catch (_) { announce("The import could not be completed. No success was recorded; check your connection and try again.", true); }
    finally { setBusy(false); }
  });
  exportButton?.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    exportButton.disabled = true;
    exportButton.setAttribute("aria-busy", "true");
    try {
      const response = await fetch("/api/students/roster/export", { credentials: "same-origin", headers: { Accept: XLSX_TYPE } });
      if (!response.ok) throw new Error("export_failed");
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = safeFilename(response.headers.get("Content-Disposition"));
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(link.href);
    } catch (_) { window.alert("Student roster export could not be downloaded. Please try again."); }
    finally { busy = false; exportButton.disabled = false; exportButton.removeAttribute("aria-busy"); }
  });
})();
