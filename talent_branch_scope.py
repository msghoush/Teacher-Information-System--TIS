"""Talent & Potential Branch ceiling (Acceptance Batch 1 closure).

The active GLOBAL Branch (the sidebar "Change Branch / Campus" selector, resolved
per request by ``auth.get_current_user`` into ``user.scope_branch_id``) is a HARD
upper ceiling for every Talent read, never just a default:

* organization/global actor with a single active Branch  -> ceiling = that Branch;
* organization/global actor whose explicit global scope is "All Branches"
  (``user.scope_all_branches``, from the ``branch_scope=all`` marker cookie) or a
  platform actor with no Branch selected                  -> no extra ceiling
  (the actor's own authorization still applies);
* Branch-limited actor                                    -> no extra ceiling (the
  accessible-Branch query already confines them to their own Branch).

The ceiling is the INTERSECTION of the actor's authorization and the active global
scope. It is computed server-side from the authenticated request user, never from
a client parameter, and is composed into the existing visible-Branch resolution so
every Talent route inherits it. A Branch outside the ceiling is treated exactly like
a Branch outside the actor's authorization (same 400/403/404 conventions as the
sibling routes) and an omitted Branch resolves to the ceiling, never to every
Branch of the organization.
"""

from __future__ import annotations

from typing import Optional

import auth
import models


def talent_branch_ceiling(user) -> Optional[int]:
    """Single Branch id the actor is confined to inside Talent, or ``None``."""
    if user is None or not auth.can_access_all_branches(user):
        return None
    if getattr(user, "scope_all_branches", False):
        return None
    scoped = getattr(user, "scope_branch_id", None)
    try:
        return int(scoped) if scoped else None
    except (TypeError, ValueError):
        return None


def branch_scope_unrestricted(user) -> bool:
    """True only for an organization/global actor with no Branch ceiling."""
    return auth.can_access_all_branches(user) and talent_branch_ceiling(user) is None


def visible_branch_ids(db, user) -> set:
    """Branch ids the actor may read inside Talent: accessible Branches within the ceiling."""
    ids = {row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()}
    ceiling = talent_branch_ceiling(user)
    if ceiling is not None:
        ids &= {ceiling}
    return ids


def visible_branch_ids_or_none(db, user) -> Optional[set]:
    """``None`` = unrestricted organization scope; otherwise the visible Branch set."""
    if branch_scope_unrestricted(user):
        return None
    return visible_branch_ids(db, user)


def branch_within_ceiling(user, branch_id) -> bool:
    ceiling = talent_branch_ceiling(user)
    return ceiling is None or (branch_id is not None and int(branch_id) == ceiling)
