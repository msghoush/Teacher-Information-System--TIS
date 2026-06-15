import os
import unittest

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"

from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import authorization
import main
import models


class PermissionEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self._seed_scope()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_scope(self):
        self.school = models.SchoolGroup(name="School A", status=True)
        self.db.add(self.school)
        self.db.flush()

        self.branch_main = models.Branch(
            name="Main Campus",
            school_group_id=self.school.id,
            status=True,
        )
        self.branch_beta = models.Branch(
            name="Beta Campus",
            school_group_id=self.school.id,
            status=True,
        )
        self.db.add_all([self.branch_main, self.branch_beta])
        self.db.flush()

        self.year = models.AcademicYear(
            school_group_id=self.school.id,
            year_name="2026-2027",
            is_active=True,
        )
        self.db.add(self.year)
        self.db.flush()

        self.admin_user = models.User(
            user_id="1001",
            username="admin_a",
            first_name="Admin",
            last_name="User",
            role=auth.ROLE_ADMINISTRATOR,
            position="Principal",
            password=auth.get_password_hash("password123"),
            school_group_id=self.school.id,
            branch_id=self.branch_main.id,
            academic_year_id=self.year.id,
            is_active=True,
        )
        self.limited_user = models.User(
            user_id="2001",
            username="limited_a",
            first_name="Limited",
            last_name="User",
            role=auth.ROLE_LIMITED,
            position="Teacher",
            password=auth.get_password_hash("password123"),
            school_group_id=self.school.id,
            branch_id=self.branch_main.id,
            academic_year_id=self.year.id,
            is_active=True,
        )
        self.inactive_user = models.User(
            user_id="3001",
            username="inactive_a",
            first_name="Inactive",
            last_name="User",
            role=auth.ROLE_ADMINISTRATOR,
            position="Principal",
            password=auth.get_password_hash("password123"),
            school_group_id=self.school.id,
            branch_id=self.branch_main.id,
            academic_year_id=self.year.id,
            is_active=False,
        )
        self.db.add_all([self.admin_user, self.limited_user, self.inactive_user])
        self.db.flush()

        self.db.add_all(
            [
                models.RolePermission(
                    school_group_id=self.school.id,
                    role=auth.ROLE_LIMITED,
                    permission_key="timetable.manage_blocks",
                    is_allowed=True,
                ),
                models.RolePermission(
                    school_group_id=self.school.id,
                    role=auth.ROLE_LIMITED,
                    permission_key="demo_requests.view",
                    is_allowed=True,
                ),
            ]
        )
        self.db.commit()

    def _build_request(self, path: str, *, method: str = "GET", user=None, accept: str = "text/html"):
        headers = []
        if accept:
            headers.append((b"accept", accept.encode("utf-8")))
        if user is not None:
            session_token = auth.create_session_token(user)
            cookie_value = "; ".join(
                [
                    f"{auth.SESSION_COOKIE_KEY}={session_token}",
                    f"branch_id={user.branch_id}",
                    f"academic_year_id={user.academic_year_id}",
                ]
            )
            headers.append((b"cookie", cookie_value.encode("utf-8")))
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
            "app": main.app,
        }
        return Request(scope)

    def test_inactive_user_session_is_rejected(self):
        request = self._build_request("/dashboard", user=self.inactive_user)
        current_user = auth.get_current_user(request, self.db)
        self.assertIsNone(current_user)
        self.assertEqual(getattr(request.state, "inactive_user_id", None), self.inactive_user.user_id)

    def test_subject_bulk_delete_requires_delete_permission(self):
        request = self._build_request(
            "/subjects/delete-bulk",
            method="POST",
            user=self.limited_user,
            accept="application/json",
        )
        denied_response = authorization.enforce_route_permission(request, self.db)
        self.assertIsNotNone(denied_response)
        self.assertEqual(denied_response.status_code, 403)

    def test_timetable_settings_page_accepts_manage_blocks_permission(self):
        request = self._build_request("/system-configuration/timetable-settings", user=self.limited_user)
        denied_response = authorization.enforce_route_permission(request, self.db)
        self.assertIsNone(denied_response)
        current_user, redirect_response = main._get_configuration_access(request, self.db)
        self.assertIsNotNone(current_user)
        self.assertIsNone(redirect_response)

    def test_demo_request_access_stays_developer_only(self):
        request = self._build_request(
            "/demo-requests",
            user=self.admin_user,
            accept="application/json",
        )
        current_user, denied_response = main._get_demo_requests_access(
            request,
            self.db,
            "demo_requests.view",
        )
        self.assertIsNone(current_user)
        self.assertIsNotNone(denied_response)
        self.assertEqual(denied_response.status_code, 403)

    def test_audit_log_route_requires_audit_export_permission(self):
        request = self._build_request(
            "/admin/audit-log",
            user=self.admin_user,
            accept="application/json",
        )
        response = main.download_audit_log(request, db=self.db)
        self.assertEqual(response.status_code, 403)

    def test_branch_scope_switch_requires_all_branch_scope_permission(self):
        request = self._build_request(
            "/scope/branch",
            method="POST",
            user=self.admin_user,
            accept="application/json",
        )
        response = main.set_scope_branch(
            request,
            branch_id=self.branch_beta.id,
            return_to="/dashboard",
            db=self.db,
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
