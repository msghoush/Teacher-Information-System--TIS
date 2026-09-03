(function () {
    "use strict";

    // Reopens whatever expandable element the user was working in before a
    // server-rendered redirect or in-place render. Target id comes from
    // either the URL fragment (redirect case: "/page#some-id") or an
    // optional inline value a page renders for a non-redirect response
    // (window.__tisReopenTargetId). Missing, stale, or invalid ids are
    // silently ignored - this never throws and never blocks page load.
    function resolveTargetId() {
        try {
            if (window.__tisReopenTargetId) {
                return String(window.__tisReopenTargetId);
            }
            var hash = window.location.hash || "";
            return hash.length > 1 ? hash.slice(1) : "";
        } catch (error) {
            return "";
        }
    }

    function reopenTarget() {
        var targetId = resolveTargetId();
        if (!targetId) {
            return;
        }

        var target;
        try {
            target = document.getElementById(targetId);
        } catch (error) {
            return;
        }
        if (!target) {
            return;
        }

        if (target.tagName === "DETAILS") {
            target.open = true;
        }

        if (typeof target.scrollIntoView === "function") {
            target.scrollIntoView({ block: "center", behavior: "smooth" });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", reopenTarget);
    } else {
        reopenTarget();
    }
})();
