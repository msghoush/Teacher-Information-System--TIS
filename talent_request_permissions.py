"""Request-scoped effective-permission checker for Talent routes.

``auth.has_permission`` recomputes the actor's whole effective-permission set
(about five SQL statements) on every call. Talent list routes ask several
questions per request (and, before this helper, per ROW). This resolves the set
lazily ONCE per checker and answers every key from it, with decisions identical
to ``auth.has_permission`` (inactive user -> False, platform owner -> True,
empty key -> True). The checker is created per request and never cached across
requests or users, so a permission change is visible on the very next request.
"""

from __future__ import annotations

from typing import Optional

import auth


def request_permission_checker(db, user, school_group_id: Optional[int] = None):
    allowed: Optional[set] = None

    def check(key: str) -> bool:
        nonlocal allowed
        cleaned = str(key or "").strip()
        if not cleaned:
            return True
        if not user or not auth.is_user_active(user):
            return False
        if auth.is_platform_owner(user):
            return True
        if allowed is None:
            allowed = set(auth.get_allowed_permission_keys(db, user, school_group_id=school_group_id))
        return cleaned in allowed

    return check


def branch_in_authorized_scope(db, user, school_group_id: int, branch_id: Optional[int]) -> bool:
    """True when ``branch_id`` is a Branch of this SchoolGroup the actor may access.

    Backend authority for an explicit Talent Branch filter: a Branch of another
    tenant, or one outside the actor's authorized Branches, can never be selected
    to widen scope (the Talent UI's global-Branch default is only a convenience).
    """
    import models

    if not branch_id:
        return False
    from talent_branch_scope import branch_within_ceiling

    if not branch_within_ceiling(user, branch_id):
        return False
    exists = db.query(models.Branch.id).filter_by(id=int(branch_id), school_group_id=int(school_group_id)).first()
    return exists is not None and auth.can_access_branch(db, user, int(branch_id))
