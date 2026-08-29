# Reduce-Only Curriculum Adjustment

The guided curriculum workflow now distinguishes period transfer from source-only reduction. Reduce-only carries an authoritative requested reduction, requires no target subject or teacher decision, and calculates each selected section from explicit-first Planning demand. Partial results stay active; zero results retire the source demand and its invalid section-level scheduling rule.

Preview and atomic apply retain scope locking, stale fingerprint checks, Draft lock validation and invalidation, rollback, audit, and immutable published history. Subject Details presents effective Current/New Planning periods and offers a `curriculum.adjust`-gated, grade-specific prefilled reduction action. Original `Subject.weekly_hours` remains catalog/default data. Multi-grade aggregation is not added because the established transaction reviews one exact subject code and subject codes are grade-specific.
