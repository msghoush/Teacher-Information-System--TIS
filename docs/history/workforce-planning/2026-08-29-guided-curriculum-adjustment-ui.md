# Guided Curriculum Adjustment UI

Stage 5 introduced the administrator-facing workflow for late-stage curriculum changes. Permissioned users can select a Current/New Planning scope, choose source and target subjects, inspect the deployed preview, make an explicit teacher decision per section, and confirm the atomic apply request.

The UI clearly separates blockers and warnings and describes Draft regeneration in customer language. If the reviewed state changes, it refreshes the preview before any apply attempt can proceed. Successful application provides navigation to Timetable and a regeneration CTA without starting generation. Backend transaction ownership, solver behavior, and published timetable history remain unchanged.
