import os
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import auth
import db_migrations
import models
import tenant_integrity
from routers import observations


class FakeRequest:
    def __init__(self, cookies):
        self.cookies = cookies
        self.state = SimpleNamespace()
        self.url = SimpleNamespace(scheme="http")


class TenantIsolationTests(unittest.TestCase):
    def setUp(self):
        os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self._seed_two_schools()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_two_schools(self):
        self.school_a = models.SchoolGroup(name="School A", status=True)
        self.school_b = models.SchoolGroup(name="School B", status=True)
        self.db.add_all([self.school_a, self.school_b])
        self.db.flush()

        self.branch_a = models.Branch(
            name="A Main",
            school_group_id=self.school_a.id,
            status=True,
        )
        self.branch_b = models.Branch(
            name="B Main",
            school_group_id=self.school_b.id,
            status=True,
        )
        self.db.add_all([self.branch_a, self.branch_b])
        self.db.flush()

        self.year_a = models.AcademicYear(
            school_group_id=self.school_a.id,
            year_name="2026-2027",
            is_active=True,
        )
        self.year_b = models.AcademicYear(
            school_group_id=self.school_b.id,
            year_name="2026-2027",
            is_active=True,
        )
        self.db.add_all([self.year_a, self.year_b])
        self.db.flush()

        self.admin_a = models.User(
            user_id="1001",
            username="admin_a",
            first_name="Admin",
            last_name="A",
            role=auth.ROLE_ADMINISTRATOR,
            position="Principal",
            password=auth.get_password_hash("password123"),
            school_group_id=self.school_a.id,
            branch_id=self.branch_a.id,
            academic_year_id=self.year_a.id,
            is_active=True,
        )
        self.teacher_user_a = models.User(
            user_id="2001",
            username="teacher_a",
            first_name="Teacher",
            last_name="A",
            role=auth.ROLE_USER,
            position="Teacher",
            password=auth.get_password_hash("password123"),
            school_group_id=self.school_a.id,
            branch_id=self.branch_a.id,
            academic_year_id=self.year_a.id,
            is_active=True,
        )
        self.admin_b = models.User(
            user_id="3001",
            username="admin_b",
            first_name="Admin",
            last_name="B",
            role=auth.ROLE_ADMINISTRATOR,
            position="Principal",
            password=auth.get_password_hash("password123"),
            school_group_id=self.school_b.id,
            branch_id=self.branch_b.id,
            academic_year_id=self.year_b.id,
            is_active=True,
        )
        self.db.add_all([self.admin_a, self.teacher_user_a, self.admin_b])
        self.db.flush()

        self.teacher_a = models.Teacher(
            teacher_id=self.teacher_user_a.user_id,
            first_name="Teacher",
            last_name="A",
            branch_id=self.branch_a.id,
            academic_year_id=self.year_a.id,
        )
        self.teacher_b = models.Teacher(
            teacher_id="4001",
            first_name="Teacher",
            last_name="B",
            branch_id=self.branch_b.id,
            academic_year_id=self.year_b.id,
        )
        self.db.add_all([self.teacher_a, self.teacher_b])
        self.db.flush()

        self.subject_a = models.Subject(
            subject_code="MAT101",
            subject_name="Math",
            weekly_hours=5,
            grade=1,
            branch_id=self.branch_a.id,
            academic_year_id=self.year_a.id,
        )
        self.subject_b = models.Subject(
            subject_code="MAT101",
            subject_name="Math",
            weekly_hours=5,
            grade=1,
            branch_id=self.branch_b.id,
            academic_year_id=self.year_b.id,
        )
        self.planning_a = models.PlanningSection(
            grade_level="1",
            section_name="A",
            class_status="Current",
            branch_id=self.branch_a.id,
            academic_year_id=self.year_a.id,
        )
        self.planning_b = models.PlanningSection(
            grade_level="1",
            section_name="A",
            class_status="Current",
            branch_id=self.branch_b.id,
            academic_year_id=self.year_b.id,
        )
        self.event_a = models.CalendarEvent(
            branch_id=self.branch_a.id,
            academic_year_id=self.year_a.id,
            title="School A Event",
            event_date="2026-09-01",
            created_by_user_id=self.admin_a.user_id,
        )
        self.event_b = models.CalendarEvent(
            branch_id=self.branch_b.id,
            academic_year_id=self.year_b.id,
            title="School B Event",
            event_date="2026-09-01",
            created_by_user_id=self.admin_b.user_id,
        )
        self.observation_a = models.Observation(
            branch_id=self.branch_a.id,
            academic_year_id=self.year_a.id,
            teacher_id=self.teacher_a.id,
            evaluator_user_id=self.admin_a.user_id,
            observation_date="2026-09-02",
        )
        self.observation_b = models.Observation(
            branch_id=self.branch_b.id,
            academic_year_id=self.year_b.id,
            teacher_id=self.teacher_b.id,
            evaluator_user_id=self.admin_b.user_id,
            observation_date="2026-09-02",
        )
        self.notification_b = models.SystemNotification(
            school_group_id=self.school_b.id,
            branch_id=self.branch_b.id,
            academic_year_id=self.year_b.id,
            recipient_user_id=self.admin_b.user_id,
            requesting_user_id=self.admin_b.user_id,
            request_type="Message",
            title="School B Only",
            status="New",
        )
        self.db.add_all(
            [
                self.subject_a,
                self.subject_b,
                self.planning_a,
                self.planning_b,
                self.event_a,
                self.event_b,
                self.observation_a,
                self.observation_b,
                self.notification_b,
            ]
        )
        self.db.commit()

    def _signed_request_for(self, user, extra_cookies=None):
        cookies = {
            auth.SESSION_COOKIE_KEY: auth.create_session_token(user),
            "branch_id": str(user.branch_id),
            "academic_year_id": str(user.academic_year_id),
        }
        cookies.update(extra_cookies or {})
        return FakeRequest(cookies)

    def test_plain_user_id_cookie_is_not_trusted(self):
        request = FakeRequest(
            {
                "user_id": self.admin_b.user_id,
                "branch_id": str(self.branch_b.id),
                "academic_year_id": str(self.year_b.id),
            }
        )

        self.assertIsNone(auth.get_current_user(request, self.db))

    def test_school_a_user_cannot_switch_to_school_b_scope_by_cookie(self):
        request = self._signed_request_for(
            self.admin_a,
            {
                "branch_id": str(self.branch_b.id),
                "academic_year_id": str(self.year_b.id),
            },
        )

        current_user = auth.get_current_user(request, self.db)

        self.assertIsNotNone(current_user)
        self.assertEqual(current_user.user_id, self.admin_a.user_id)
        self.assertEqual(current_user.scope_school_group_id, self.school_a.id)
        self.assertEqual(current_user.scope_branch_id, self.branch_a.id)
        self.assertEqual(current_user.scope_academic_year_id, self.year_a.id)

    def test_notification_recipients_are_limited_to_current_branch_scope(self):
        current_user = auth.get_current_user(self._signed_request_for(self.admin_a), self.db)

        recipient_ids = {
            user.user_id
            for user in auth.get_notification_recipient_query(self.db, current_user).all()
        }

        self.assertIn(self.admin_a.user_id, recipient_ids)
        self.assertIn(self.teacher_user_a.user_id, recipient_ids)
        self.assertNotIn(self.admin_b.user_id, recipient_ids)

    def test_observation_direct_id_access_is_scoped(self):
        current_user = auth.get_current_user(self._signed_request_for(self.admin_a), self.db)

        own_observation = observations._get_observation_for_current_scope(
            self.db,
            current_user,
            self.observation_a.id,
        )
        cross_school_observation = observations._get_observation_for_current_scope(
            self.db,
            current_user,
            self.observation_b.id,
        )

        self.assertIsNotNone(own_observation)
        self.assertIsNone(cross_school_observation)

    def test_teacher_access_stays_limited_to_own_observations(self):
        current_teacher_user = auth.get_current_user(
            self._signed_request_for(self.teacher_user_a),
            self.db,
        )

        own_observation = observations._get_observation_for_current_scope(
            self.db,
            current_teacher_user,
            self.observation_a.id,
        )
        cross_school_observation = observations._get_observation_for_current_scope(
            self.db,
            current_teacher_user,
            self.observation_b.id,
        )

        self.assertIsNotNone(own_observation)
        self.assertIsNone(cross_school_observation)

    def test_branch_year_mismatch_is_rejected(self):
        current_user = auth.get_current_user(self._signed_request_for(self.admin_a), self.db)

        self.assertTrue(
            auth.validate_branch_year_scope(
                self.db,
                branch_id=self.branch_a.id,
                academic_year_id=self.year_a.id,
                current_user=current_user,
            )
        )
        self.assertFalse(
            auth.validate_branch_year_scope(
                self.db,
                branch_id=self.branch_a.id,
                academic_year_id=self.year_b.id,
                current_user=current_user,
            )
        )

    def test_major_operational_models_filter_by_branch_and_year(self):
        scope = {
            "branch_id": self.branch_a.id,
            "academic_year_id": self.year_a.id,
        }

        scoped_subjects = self.db.query(models.Subject).filter_by(**scope).all()
        scoped_teachers = self.db.query(models.Teacher).filter_by(**scope).all()
        scoped_planning = self.db.query(models.PlanningSection).filter_by(**scope).all()
        scoped_events = self.db.query(models.CalendarEvent).filter_by(**scope).all()
        scoped_observations = self.db.query(models.Observation).filter_by(**scope).all()

        self.assertEqual([self.subject_a.id], [row.id for row in scoped_subjects])
        self.assertEqual([self.teacher_a.id], [row.id for row in scoped_teachers])
        self.assertEqual([self.planning_a.id], [row.id for row in scoped_planning])
        self.assertEqual([self.event_a.id], [row.id for row in scoped_events])
        self.assertEqual([self.observation_a.id], [row.id for row in scoped_observations])

    def test_route_surface_scope_patterns_exclude_school_b_records(self):
        current_user = auth.get_current_user(self._signed_request_for(self.admin_a), self.db)
        branch_id = current_user.scope_branch_id
        academic_year_id = current_user.scope_academic_year_id

        route_models = [
            models.Subject,
            models.Teacher,
            models.PlanningSection,
            models.CalendarEvent,
            models.Observation,
        ]
        for model in route_models:
            school_b_id = getattr(self, {
                models.Subject: "subject_b",
                models.Teacher: "teacher_b",
                models.PlanningSection: "planning_b",
                models.CalendarEvent: "event_b",
                models.Observation: "observation_b",
            }[model]).id
            self.assertIsNone(
                self.db.query(model).filter(
                    model.id == school_b_id,
                    model.branch_id == branch_id,
                    model.academic_year_id == academic_year_id,
                ).first(),
                f"{model.__tablename__} direct-id lookup must stay in active branch/year scope",
            )
            bulk_ids = {
                row.id
                for row in self.db.query(model.id).filter(
                    model.id.in_([getattr(self, {
                        models.Subject: "subject_a",
                        models.Teacher: "teacher_a",
                        models.PlanningSection: "planning_a",
                        models.CalendarEvent: "event_a",
                        models.Observation: "observation_a",
                    }[model]).id, school_b_id]),
                    model.branch_id == branch_id,
                    model.academic_year_id == academic_year_id,
                ).all()
            }
            self.assertNotIn(school_b_id, bulk_ids)

        user_ids = {
            user.user_id
            for user in auth.filter_user_query_by_school_group(
                self.db,
                self.db.query(models.User),
                current_user.scope_school_group_id,
            ).all()
        }
        self.assertIn(self.admin_a.user_id, user_ids)
        self.assertNotIn(self.admin_b.user_id, user_ids)

        branch_ids = {
            branch.id
            for branch in self.db.query(models.Branch).filter(
                models.Branch.school_group_id == current_user.scope_school_group_id
            ).all()
        }
        year_ids = {
            year.id
            for year in self.db.query(models.AcademicYear).filter(
                models.AcademicYear.school_group_id == current_user.scope_school_group_id
            ).all()
        }
        self.assertEqual({self.branch_a.id}, branch_ids)
        self.assertEqual({self.year_a.id}, year_ids)

    def test_fixture_has_no_tenant_integrity_issues(self):
        self.assertEqual([], tenant_integrity.collect_tenant_integrity_issues(self.db))

    def test_production_requires_real_session_secret_and_secure_cookies(self):
        old_secret = os.environ.pop("TIS_SESSION_SECRET", None)
        old_env = os.environ.get("TIS_ENV")
        old_cookie_secure = os.environ.get("TIS_COOKIE_SECURE")
        try:
            os.environ["TIS_ENV"] = "production"
            os.environ["TIS_COOKIE_SECURE"] = "0"
            self.assertTrue(auth.should_use_secure_cookies(FakeRequest({})))
            with self.assertRaises(RuntimeError):
                auth.create_session_token(self.admin_a)
            with self.assertRaises(RuntimeError):
                auth.validate_security_configuration()
        finally:
            if old_secret is not None:
                os.environ["TIS_SESSION_SECRET"] = old_secret
            else:
                os.environ.pop("TIS_SESSION_SECRET", None)
            if old_env is not None:
                os.environ["TIS_ENV"] = old_env
            else:
                os.environ.pop("TIS_ENV", None)
            if old_cookie_secure is not None:
                os.environ["TIS_COOKIE_SECURE"] = old_cookie_secure
            else:
                os.environ.pop("TIS_COOKIE_SECURE", None)

    def test_tenant_scope_migration_adds_and_backfills_columns(self):
        legacy_engine = create_engine("sqlite:///:memory:")
        try:
            with legacy_engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE school_groups ("
                        "id INTEGER PRIMARY KEY, "
                        "name VARCHAR(160) NOT NULL UNIQUE, "
                        "status BOOLEAN NOT NULL, "
                        "created_at DATETIME, "
                        "updated_at DATETIME)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE branches ("
                        "id INTEGER PRIMARY KEY, "
                        "name VARCHAR NOT NULL, "
                        "location VARCHAR, "
                        "status BOOLEAN)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE academic_years ("
                        "id INTEGER PRIMARY KEY, "
                        "year_name VARCHAR NOT NULL, "
                        "is_active BOOLEAN)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE users ("
                        "id INTEGER PRIMARY KEY, "
                        "user_id VARCHAR(10), "
                        "username VARCHAR(50), "
                        "first_name VARCHAR, "
                        "last_name VARCHAR, "
                        "position VARCHAR(50), "
                        "password VARCHAR, "
                        "role VARCHAR, "
                        "branch_id INTEGER, "
                        "academic_year_id INTEGER, "
                        "is_active BOOLEAN)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE system_notifications ("
                        "id INTEGER PRIMARY KEY, "
                        "recipient_user_id VARCHAR(10) NOT NULL, "
                        "requesting_user_id VARCHAR(10), "
                        "request_type VARCHAR(80), "
                        "title VARCHAR(160), "
                        "status VARCHAR(20))"
                    )
                )
                connection.execute(text("INSERT INTO branches (id, name, status) VALUES (1, 'Legacy Branch', 1)"))
                connection.execute(text("INSERT INTO academic_years (id, year_name, is_active) VALUES (1, '2026-2027', 1)"))
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, user_id, username, branch_id, academic_year_id, is_active) "
                        "VALUES (1, '1001', 'legacy', 1, 1, 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO system_notifications "
                        "(id, recipient_user_id, request_type, title, status) "
                        "VALUES (1, '1001', 'Message', 'Hello', 'New')"
                    )
                )

            applied = db_migrations.run_pending_migrations(legacy_engine)
            inspector = inspect(legacy_engine)
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            notification_columns = {
                column["name"]
                for column in inspector.get_columns("system_notifications")
            }
            self.assertIn("20260613_001_tenant_scope_columns", applied)
            self.assertIn("school_group_id", user_columns)
            self.assertIn("school_group_id", notification_columns)
            self.assertIn("branch_id", notification_columns)
            self.assertIn("academic_year_id", notification_columns)
            with legacy_engine.begin() as connection:
                self.assertIsNotNone(connection.execute(text("SELECT school_group_id FROM users WHERE id = 1")).scalar())
                self.assertIsNotNone(
                    connection.execute(text("SELECT school_group_id FROM system_notifications WHERE id = 1")).scalar()
                )
                self.assertEqual(
                    1,
                    connection.execute(text("SELECT branch_id FROM system_notifications WHERE id = 1")).scalar(),
                )
        finally:
            legacy_engine.dispose()


if __name__ == "__main__":
    unittest.main()
