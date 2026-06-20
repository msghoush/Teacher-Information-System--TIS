(() => {
    const MAX_VISIBLE_WORDS = 3;
    // Precise selectors cover established components; semantic rules below catch page-specific variants.
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
        "p",
        "small",
        "[class*='description']",
        "[class*='subtitle']",
        "[class*='-note']",
        "[class*='-lede']",
        "button [class*='copy'] > span",
        "a [class*='copy'] > span",
        "[role='button'] [class*='copy'] > span",
    ].join(", ");
    const DESCRIPTION_CLASS_PATTERN = /(?:^|[-_])(description|subtitle|note|lede|supporting|helper)(?:$|[-_])/i;
    const COMPONENT_CLASS_PATTERN = /(?:^|[-_])(card|action|quick|summary|banner|hero|tile|panel|toolbar|workspace|inspector)(?:$|[-_])/i;
    const HEADING_CONTEXT_CLASS_PATTERN = /(?:^|[-_])(copy|head|header|title|intro|hero|toolbar)(?:$|[-_])/i;
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

    const classListMatches = (element, pattern) => (
        element instanceof Element
        && Array.from(element.classList).some((className) => pattern.test(className))
    );

    const isSemanticComponent = (element) => (
        element instanceof Element
        && (
            element.matches(KNOWN_COMPONENT_SELECTOR)
            || classListMatches(element, COMPONENT_CLASS_PATTERN)
        )
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

    const hasDirectHeading = (element) => Array.from(element.children).some((child) => (
        /^H[1-6]$/.test(child.tagName)
    ));

    const isLeafDescription = (element) => (
        classListMatches(element, DESCRIPTION_CLASS_PATTERN)
        && !element.querySelector("h1, h2, h3, h4, h5, h6, p, small, button, a, input, select, textarea")
    );

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
        if (element.matches(KNOWN_DESCRIPTION_SELECTOR)) {
            return true;
        }

        const tagName = element.tagName;
        const parent = element.parentElement;
        const components = componentAncestors(element);
        const insideInteractiveAction = Boolean(element.closest("button, a, [role='button']"));

        if (insideInteractiveAction) {
            if (tagName === "P" || tagName === "SMALL" || isLeafDescription(element)) {
                return true;
            }
            if (tagName === "SPAN" && parent && classListMatches(parent, HEADING_CONTEXT_CLASS_PATTERN)) {
                return true;
            }
        }
        if (isLeafDescription(element) && components.length > 0) {
            return true;
        }
        if (tagName === "P" && parent) {
            if (hasDirectHeading(parent) || isSemanticComponent(parent)) {
                return true;
            }
            if (classListMatches(parent, HEADING_CONTEXT_CLASS_PATTERN) && components.length > 0) {
                return true;
            }
        }
        if (tagName === "SMALL" && components.length > 0 && parent) {
            if (
                isSemanticComponent(parent)
                || hasDirectHeading(parent)
                || parent.querySelector(":scope > strong, :scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6")
                || classListMatches(parent, HEADING_CONTEXT_CLASS_PATTERN)
            ) {
                return true;
            }
        }
        return false;
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
        const trigger = description.querySelector(".compact-description-trigger");
        if (!trigger) {
            return;
        }
        const triggerRect = trigger.getBoundingClientRect();
        const tooltipWidth = Math.min(300, window.innerWidth - 32);
        description.classList.toggle(
            "align-tooltip-right",
            triggerRect.left + tooltipWidth > window.innerWidth - 16
        );
    };

    const showTooltip = (description) => {
        alignTooltip(description);
        description.classList.add("is-tooltip-open");
        description.querySelector(".compact-description-trigger")?.setAttribute("aria-expanded", "true");
    };

    const hideTooltip = (description, force = false) => {
        if (!force && description.classList.contains("is-tooltip-pinned")) {
            return;
        }
        description.classList.remove("is-tooltip-open");
        description.querySelector(".compact-description-trigger")?.setAttribute("aria-expanded", "false");
    };

    const closeAllTooltips = () => {
        document.querySelectorAll(".compact-description.is-tooltip-open").forEach((description) => {
            description.classList.remove("is-tooltip-pinned");
            hideTooltip(description, true);
        });
    };

    const enhanceDescription = (description) => {
        if (!isDescriptionCandidate(description)) {
            return;
        }
        if (description.querySelector(":scope > .compact-description-trigger")) {
            return;
        }

        const text = normalizedText(description);
        description.classList.remove(
            "compact-description",
            "is-tooltip",
            "is-tooltip-open",
            "is-tooltip-pinned",
            "align-tooltip-right"
        );

        if (!text || wordCount(text) <= MAX_VISIBLE_WORDS) {
            refreshComponentState(description);
            return;
        }

        tooltipSequence += 1;
        const tooltipId = `compact-description-tooltip-${tooltipSequence}`;
        const trigger = document.createElement("span");
        const tooltip = document.createElement("span");

        trigger.className = "compact-description-trigger";
        trigger.tabIndex = 0;
        trigger.setAttribute("role", "button");
        trigger.setAttribute("aria-label", "Show description");
        trigger.setAttribute("aria-describedby", tooltipId);
        trigger.setAttribute("aria-expanded", "false");
        trigger.textContent = "i";

        tooltip.id = tooltipId;
        tooltip.className = "compact-description-tooltip";
        tooltip.setAttribute("role", "tooltip");
        tooltip.textContent = text;

        description.textContent = "";
        description.classList.add("compact-description", "is-tooltip");
        description.append(trigger, tooltip);

        trigger.addEventListener("mouseenter", () => showTooltip(description));
        trigger.addEventListener("mouseleave", () => hideTooltip(description));
        trigger.addEventListener("focus", () => showTooltip(description));
        trigger.addEventListener("blur", () => hideTooltip(description));
        trigger.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const shouldPin = !description.classList.contains("is-tooltip-pinned");
            closeAllTooltips();
            if (shouldPin) {
                description.classList.add("is-tooltip-pinned");
                showTooltip(description);
            }
        });
        trigger.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                description.classList.remove("is-tooltip-pinned");
                hideTooltip(description, true);
                trigger.blur();
                return;
            }
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                trigger.click();
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
        if (event.target.closest(".compact-description")) {
            return;
        }
        closeAllTooltips();
    });
})();
