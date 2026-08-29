# Curriculum Transfer and Subjects Display Correction

The curriculum adjustment contract now preserves the administrator's requested transfer count from the guided UI through preview fingerprinting and atomic apply. Each section derives source and target results from its current effective Planning demand. Non-positive transfers are rejected, requests larger than a section's source demand block preview, partial transfers keep the source active, and only a zero result retires it.

The Subjects list now reads explicit-first `PlanningSubjectDemand` for Current/New sections in the selected branch and academic year. Uniform grade-subject demand is shown as the effective Planning weekly-period value. When sections differ, the list shows **Varies** and exposes each section's value. The catalog `Subject.weekly_hours` value remains unchanged and serves only as fallback/default context.
