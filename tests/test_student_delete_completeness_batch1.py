"""Batch 1: exhaustive foreign-key audit guard for permanent Student deletion.

Owner data-integrity rule: when a Student is permanently deleted, everything the
Student owns in Student-domain and Talent & Potential must be deleted in the same
transaction, so nothing orphaned can feed current analytics. This locks the
deletion list against the ORM metadata: adding a new table that references a
Student (directly, or transitively through Talent rows) without teaching
``force_delete_student_history`` about it fails here.
"""

import models
from database import Base
from student_academic_service import STUDENT_OWNED_MODELS

# Tables that reference a Student but are deliberately not Student-owned data.
INTENTIONAL_NON_OWNED = set()


def _student_referencing_tables():
    direct = set()
    for table in Base.metadata.tables.values():
        if table.name == "students":
            continue
        if "student_id" in table.c or any(fk.column.table.name == "students" for fk in table.foreign_keys):
            direct.add(table.name)
    return direct


def _transitive_dependents(seed_tables):
    frontier = set(seed_tables) | {"students"}
    found = set()
    changed = True
    while changed:
        changed = False
        for table in Base.metadata.tables.values():
            if table.name in frontier:
                continue
            if any(fk.column.table.name in frontier for fk in table.foreign_keys):
                frontier.add(table.name)
                found.add(table.name)
                changed = True
    return found


def test_force_delete_covers_every_table_that_references_a_student():
    owned = {model.__tablename__ for model in STUDENT_OWNED_MODELS}
    assert _student_referencing_tables() - INTENTIONAL_NON_OWNED == owned


def test_no_table_reaches_a_student_only_transitively():
    """A table that references only a Student-owned row (not the Student) would survive deletion."""
    assert _transitive_dependents(_student_referencing_tables()) == set()


def test_student_owned_models_are_ordered_children_before_parents():
    """FK-safe order: every table is deleted before any table it is referenced by."""
    order = [model.__tablename__ for model in STUDENT_OWNED_MODELS]
    for table in (Base.metadata.tables[name] for name in order):
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent in order and parent != table.name:
                assert order.index(table.name) < order.index(parent), (table.name, "must be deleted before", parent)


def test_every_student_owned_model_is_scoped_by_school_group_and_student_id():
    for model in STUDENT_OWNED_MODELS:
        columns = set(model.__table__.c.keys())
        assert {"school_group_id", "student_id"} <= columns, model.__name__
