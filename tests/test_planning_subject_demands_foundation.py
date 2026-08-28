from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from database import Base
from planning_subject_demand_service import resolve_section_subject_demands
from routers.planning import _get_subject_alignment_map


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _seed(db):
    db.add_all([
        models.SchoolGroup(id=1, name="Group One"),
        models.SchoolGroup(id=2, name="Group Two"),
    ])
    db.commit()
    db.add_all([
        models.Branch(id=10, school_group_id=1, name="Branch A"),
        models.Branch(id=20, school_group_id=2, name="Branch B"),
        models.AcademicYear(id=100, year_name="Year A", school_group_id=1),
        models.AcademicYear(id=200, year_name="Year B", school_group_id=2),
    ])
    db.commit()
    db.add_all([
        models.Subject(id=1000, subject_code="SOC3", subject_name="Social Studies", weekly_hours=1, grade=3, branch_id=10, academic_year_id=100),
        models.Subject(id=1001, subject_code="WEL3", subject_name="Well Being", weekly_hours=1, grade=3, branch_id=10, academic_year_id=100),
        models.Subject(id=2000, subject_code="SOC3", subject_name="Social Studies", weekly_hours=4, grade=3, branch_id=20, academic_year_id=200),
        models.PlanningSection(id=3000, grade_level="3", section_name="A", class_status="Current", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=3001, grade_level="3", section_name="B", class_status="New", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=3002, grade_level="3", section_name="C", class_status="Closed", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=4000, grade_level="3", section_name="A", class_status="Current", branch_id=20, academic_year_id=200),
    ])
    db.commit()


def test_backfill_is_scoped_current_new_and_idempotent():
    engine, db = _database()
    _seed(db)
    with engine.begin() as connection:
        db_migrations._planning_subject_demands_foundation(engine, connection)
        db_migrations._planning_subject_demands_foundation(engine, connection)

    rows = db.query(models.PlanningSubjectDemand).order_by(models.PlanningSubjectDemand.id).all()
    assert {(row.planning_section_id, row.subject_code, row.weekly_periods) for row in rows} == {
        (3000, "SOC3", 1), (3000, "WEL3", 1),
        (3001, "SOC3", 1), (3001, "WEL3", 1),
        (4000, "SOC3", 4),
    }
    assert not any(row.planning_section_id == 3002 for row in rows)
    assert all((row.branch_id, row.academic_year_id) in {(10, 100), (20, 200)} for row in rows)


def test_only_one_active_demand_per_section_subject_and_retired_history_is_supported():
    _, db = _database()
    _seed(db)
    retired = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3000,
        subject_code="SOC3", weekly_periods=0, is_active=False,
    )
    active = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3000,
        subject_code="SOC3", weekly_periods=1, is_active=True,
    )
    db.add_all([retired, active])
    db.commit()
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3000,
        subject_code="SOC3", weekly_periods=2, is_active=True,
    ))
    try:
        db.commit()
        assert False, "expected active demand uniqueness failure"
    except IntegrityError:
        db.rollback()


def test_backfill_does_not_reactivate_an_explicitly_retired_demand():
    engine, db = _database()
    _seed(db)
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3000,
        subject_code="SOC3", weekly_periods=0, is_active=False,
    ))
    db.commit()
    with engine.begin() as connection:
        db_migrations._planning_subject_demands_foundation(engine, connection)
    rows = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=3000, subject_code="SOC3"
    ).all()
    assert len(rows) == 1
    assert rows[0].is_active is False


def test_explicit_rows_override_legacy_and_retirement_suppresses_fallback():
    _, db = _database()
    _seed(db)
    fallback = resolve_section_subject_demands(
        db, branch_id=10, academic_year_id=100, planning_section_id=3000,
    )
    assert {(row.subject_code, row.weekly_periods, row.authority) for row in fallback} == {
        ("SOC3", 1, "legacy_fallback"), ("WEL3", 1, "legacy_fallback")
    }
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3000,
        subject_code="SOC3", weekly_periods=0, is_active=False,
    ))
    db.commit()
    resolved = resolve_section_subject_demands(
        db, branch_id=10, academic_year_id=100, planning_section_id=3000,
    )
    by_code = {row.subject_code: row for row in resolved}
    assert by_code["SOC3"].authority == "explicit"
    assert by_code["SOC3"].is_active is False
    assert by_code["SOC3"].weekly_periods == 0
    assert by_code["WEL3"].authority == "legacy_fallback"


def test_demand_rejects_cross_scope_section_or_subject_identity():
    _, db = _database()
    _seed(db)
    db.add(models.PlanningSubjectDemand(
        branch_id=20, academic_year_id=200, planning_section_id=3000,
        subject_code="SOC3", weekly_periods=4, is_active=True,
    ))
    try:
        db.commit()
        assert False, "expected composite section scope failure"
    except IntegrityError:
        db.rollback()


def test_existing_timetable_authority_still_uses_subject_weekly_hours():
    _, db = _database()
    _seed(db)
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3000,
        subject_code="SOC3", weekly_periods=0, is_active=False,
    ))
    db.commit()
    aligned = _get_subject_alignment_map(db, 10, 100)
    assert {(item["subject_code"], item["weekly_hours"]) for item in aligned["3"]} == {
        ("SOC3", 1), ("WEL3", 1)
    }


def test_migration_is_registered():
    assert any(
        item.migration_id == "20260828_004_planning_subject_demands_foundation"
        for item in db_migrations.MIGRATIONS
    )


def test_migration_is_safe_when_legacy_schema_has_no_planning_tables():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        db_migrations._planning_subject_demands_foundation(engine, connection)
