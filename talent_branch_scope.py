"""Talent & Potential Branch authority.

Owner-directed amendment (Part 1 production follow-up, 2026-09-25) to the Batch 1
closure: the sidebar Branch is no longer a Talent ceiling for an organization-
authorized actor. It is only the DEFAULT page-level Branch (rendered as
tp-config.branch and pre-selected in the Talent Branch filter).

* organization/global actor (auth.can_access_all_branches) -> the ceiling is the
  actor's own authorization: every Branch of their SchoolGroup. They may choose All
  Branches (omit branch_id) or any single authorized Branch inside a Talent page;
* Branch-limited actor -> the ceiling stays their authorized Branch(es), enforced by
  auth.get_accessible_branch_query; they can never widen it;
* an explicit branch_id is always validated server-side against the visible set
  (a foreign, unauthorized or cross-tenant Branch is rejected exactly as before);
* the legacy branch_scope=all marker cookie is ignored: it grants nothing.

The ceiling is computed server-side from the authenticated request user, never from a
client parameter, and is composed into the existing visible-Branch resolution so every
Talent route inherits it. There is no second authorization system.
"""

from __future__ import annotations

from typing import Optional

import auth
import models


def talent_branch_ceiling(user) -> Optional[int]:
    """Extra single-Branch ceiling beyond the actor's authorization.

    Always None: the sidebar Branch is a default, not a ceiling. A Branch-limited
    actor is confined by the accessible-Branch query itself.
    """
    return None


def branch_scope_unrestricted(user) -> bool:
    """True only for an organization/global actor (all Branches of their SchoolGroup)."""
    return bool(user is not None and auth.can_access_all_branches(user))


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
