(() => {
    const MAX_VISIBLE_WORDS = 3;
    // Only established components and explicit data attributes opt in.
    const KNOWN_COMPONENT_SELECTOR = [
        ".tis-kpi-card",
        ".config-module-card",
        ".teacher-workflow-card",
        ".allocation-metric-card",
        ".teacher-load-stat-card",
        ".report-focus-card",
        ".report-mini-stat",
        ".report-decision-card",
        ".report-visual-card",
        ".report-card",
        ".report-coverage-highlight-card",
        ".subject-pool-summary-item",
        ".subject-pool-stat",
        ".assignment-suggestion-stat",
        ".year-row",
    ].join(", ");
    const KNOWN_DESCRIPTION_SELECTOR = [
        ".tis-kpi-card > small",
        ".tis-kpi-card > p",
        ".config-module-card > p",
        ".teacher-workflow-card > p",
        ".allocation-metric-card > small",
        ".teacher-load-stat-card > small",
        ".report-focus-card > p",
        ".report-mini-stat > small",
        ".report-decision-card > p",
        ".report-visual-card > p",
        ".report-card-head-copy > p",
        ".report-coverage-highlight-card > small",
        ".subject-pool-summary-item > small",
        ".subject-pool-stat > small",
        ".assignment-suggestion-stat > small",
        ".year-row .year-copy > p",
    ].join(", ");
    const DESCRIPTION_TEXT_SELECTOR = [
        "[data-compact-description]",
        KNOWN_DESCRIPTION_SELECTOR,
    ].join(", ");
    const DIRECT_BANNER_SELECTOR = [
        ".notice-banner",
        ".calendar-banner.is-notice",
        ".banner.is-info",
        ".shell-notice",
    ].join(", ");
    // Operational help, validation, and authored record content should remain immediately readable.
    const EXCLUDED_DESCRIPTION_SELECTOR = [
        "[data-compact-description='off']",
        ".hint",
        ".field-note",
        ".field-help",
        ".field-hint",
        ".assignment-note",
        ".locked-note",
        ".lock-note",
        ".error",
        ".empty",
        ".empty-note",
        ".empty-state",
        ".flash-note",
        ".assignment-suggestion-progress-note",
        ".modal-body",
        ".notification-popup-message",
        ".notification-note-content",
        ".criterion-title",
        ".self-criterion-title",
        ".result-panel > p",
        ".performance-recommendation",
        ".sidebar-photo-help",
        ".logo-spec",
        ".compact-description-trigger",
        ".compact-description-tooltip",
    ].join(", ");

    let tooltipSequence = 0;
    const pendingDescriptions = new Set();
    let updateScheduled = false;

    const normalizedText = (element) => element.textContent.replace(/\s+/g, " ").trim();
    const wordCount = (text) => (text.match(/\S+/g) || []).length;

    const isSemanticComponent = (element) => (
        element instanceof Element
        && element.matches(KNOWN_COMPONENT_SELECTOR)
    );

    const componentAncestors = (element) => {
        const components = [];
        let current = element.parentElement;
        while (current && !current.classList.contains("page-stage")) {
            if (isSemanticComponent(current)) {
                components.push(current);
            }
            current = current.parentElement;
        }
        return components;
    };

    const isDescriptionCandidate = (element) => {
        if (!(element instanceof Element) || !element.closest(".page-stage")) {
            return false;
        }
        if (element.closest("[data-compact-description='off']") || element.matches(EXCLUDED_DESCRIPTION_SELECTOR)) {
            return false;
        }
        if (element.hasAttribute("data-compact-description")) {
            return true;
        }
        return element.matches(KNOWN_DESCRIPTION_SELECTOR);
    };

    const prepareDirectBannerDescriptions = (root) => {
        if (!(root instanceof Element) && root !== document) {
            return;
        }
        const banners = [];
        if (root instanceof Element && root.matches(DIRECT_BANNER_SELECTOR)) {
            banners.push(root);
        }
        root.querySelectorAll(DIRECT_BANNER_SELECTOR).forEach((banner) => banners.push(banner));

        banners.forEach((banner) => {
            const textNodes = Array.from(banner.childNodes).filter((node) => (
                node.nodeType === Node.TEXT_NODE && node.textContent.trim()
            ));
            if (textNodes.length === 0) {
                return;
            }
            const descriptionText = textNodes
                .map((node) => node.textContent.trim())
                .filter(Boolean)
                .join(" ");
            textNodes.forEach((node) => node.remove());
            const description = document.createElement("span");
            description.setAttribute("data-compact-description", "true");
            description.textContent = descriptionText;
            banner.appendChild(description);
        });
    };

    const refreshComponentState = (element) => {
        componentAncestors(element).forEach((component) => {
            component.classList.toggle(
                "has-compact-description-tooltip",
                Boolean(component.querySelector(".compact-description.is-tooltip"))
            );
        });
    };

    const alignTooltip = (description) => {
        const surface = description._compactTooltipSurface;
        if (!surface) {
            return;
        }
        const surfaceRect = surface.getBoundingClientRect();
        const tooltipWidth = Math.min(300, window.innerWidth - 32);
        description.classList.toggle(
            "align-tooltip-right",
            surfaceRect.left + tooltipWidth > window.innerWidth - 16
        );
    };

    const showTooltip = (description) => {
        alignTooltip(description);
        description.classList.add("is-tooltip-open");
    };

    const hideTooltip = (description) => {
        description.classList.remove("is-tooltip-open");
    };

    const closeAllTooltips = () => {
        document.querySelectorAll(".compact-description.is-tooltip-open").forEach((description) => {
            hideTooltip(description);
        });
    };

    const enhanceDescription = (description) => {
        if (!isDescriptionCandidate(description)) {
            return;
        }
        if (description.querySelector(":scope > .compact-description-tooltip")) {
            return;
        }

        const text = normalizedText(description);
        description.classList.remove(
            "compact-description",
            "is-tooltip",
            "is-tooltip-open",
            "align-tooltip-right"
        );

        if (!text || wordCount(text) <= MAX_VISIBLE_WORDS) {
            refreshComponentState(description);
            return;
        }

        tooltipSequence += 1;
        const tooltipId = `compact-description-tooltip-${tooltipSequence}`;
        const tooltip = document.createElement("span");

        tooltip.id = tooltipId;
        tooltip.className = "compact-description-tooltip";
        tooltip.setAttribute("role", "tooltip");
        tooltip.textContent = text;

        description.textContent = "";
        description.classList.add("compact-description", "is-tooltip");
        description.append(tooltip);

        const surface = componentAncestors(description)[0] || description.parentElement;
        if (!surface) {
            return;
        }
        description._compactTooltipSurface = surface;
        surface.classList.add("has-compact-description-tooltip");
        const describedBy = new Set((surface.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
        describedBy.add(tooltipId);
        surface.setAttribute("aria-describedby", Array.from(describedBy).join(" "));

        surface.addEventListener("mouseenter", () => showTooltip(description));
        surface.addEventListener("mouseleave", () => hideTooltip(description));
        surface.addEventListener("focusin", () => showTooltip(description));
        surface.addEventListener("focusout", (event) => {
            if (!surface.contains(event.relatedTarget)) {
                hideTooltip(description);
            }
        });
        surface.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                hideTooltip(description);
            }
        });

        refreshComponentState(description);
    };

    const collectDescriptions = (root) => {
        if (!(root instanceof Element) && root !== document) {
            return;
        }
        if (root instanceof Element && root.matches(DESCRIPTION_TEXT_SELECTOR)) {
            pendingDescriptions.add(root);
        }
        root.querySelectorAll(DESCRIPTION_TEXT_SELECTOR).forEach((element) => {
            pendingDescriptions.add(element);
        });
    };

    const scheduleEnhancement = () => {
        if (updateScheduled) {
            return;
        }
        updateScheduled = true;
        queueMicrotask(() => {
            updateScheduled = false;
            const descriptions = Array.from(pendingDescriptions);
            pendingDescriptions.clear();
            descriptions.forEach(enhanceDescription);
        });
    };

    prepareDirectBannerDescriptions(document);
    collectDescriptions(document);
    scheduleEnhancement();

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === "characterData") {
                prepareDirectBannerDescriptions(mutation.target.parentElement);
                collectDescriptions(mutation.target.parentElement);
                return;
            }
            prepareDirectBannerDescriptions(mutation.target);
            collectDescriptions(mutation.target);
            mutation.addedNodes.forEach((node) => {
                prepareDirectBannerDescriptions(node);
                collectDescriptions(node);
            });
        });
        scheduleEnhancement();
    });
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });

    document.addEventListener("click", (event) => {
        if (event.target.closest(".has-compact-description-tooltip")) {
            return;
        }
        closeAllTooltips();
    });
})();
