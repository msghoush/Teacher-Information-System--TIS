"""Single access rule for the organization-level Talent & Potential configuration surface.

System Configuration > Talent & Potential is where organization-wide Talent
configuration (Programs, eligible Grades, Rubrics/Competencies/Levels, KPI and
Evaluation Plans/Periods) is defined. Authority is EXACTLY the authority the
canonical mutation routes already enforce (final-closure Part B): an existing
semantic Talent configuration permission AND organization/global access scope.
No new permission key exists; this module only names the rule so the System
Configuration registry, the page route and the operational Talent pages agree.
UI visibility never replaces the API gates, which remain authoritative.
"""

from urllib.parse import urlencode

import auth

TALENT_CONFIGURATION_PATH = "/system-configuration/talent-potential"
# Same keys the Program / Evaluation Plan routers treat as configuration mutation.
TALENT_CONFIGURATION_KEYS = ("talent_programs.manage", "talent_evaluation_plans.manage")
TALENT_CONFIGURATION_TABS = ("programs", "evaluation-periods")


def is_authorized(user, allowed_keys) -> bool:
    """True only for an organization/global-scoped actor holding a configuration key."""
    if user is None or not auth.can_access_all_branches(user):
        return False
    return any(key in allowed_keys for key in TALENT_CONFIGURATION_KEYS)


def configuration_url(*, tab: str = "", program_id=None, academic_year_id=None) -> str:
    """Deep link into the configuration workspace (digits-only ids, allow-listed tab)."""
    query = {}
    if tab in TALENT_CONFIGURATION_TABS:
        query["tab"] = tab
    if str(program_id or "").isdigit():
        query["program_id"] = str(int(program_id))
    if str(academic_year_id or "").isdigit():
        query["academic_year_id"] = str(int(academic_year_id))
    return TALENT_CONFIGURATION_PATH + (f"?{urlencode(query)}" if query else "")
