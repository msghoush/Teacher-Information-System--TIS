import asyncio
import json
import os
import re
import tempfile
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, unquote_plus, urlparse

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"

from starlette.requests import Request
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import auth
import audit
import authorization
import db_migrations
import main
import models
import permission_registry
import saas.models as saas_models
import tenant_integrity
from routers import observations, subjects, teachers, users
from ui_shell import build_shell_context


class PlatformAccessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self._seed()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed(self):
        self.group_a = models.SchoolGroup(name="Group A", status=True)
        self.group_b = models.SchoolGroup(name="Group B", status=True)
        self.db.add_all([self.group_a, self.group_b])
        self.db.flush()
        self.branch_a1 = models.Branch(name="A1", school_group_id=self.group_a.id, status=True)
        self.branch_a2 = models.Branch(name="A2", school_group_id=self.group_a.id, status=True)
        self.branch_b1 = models.Branch(name="B1", school_group_id=self.group_b.id, status=True)
        self.branch_b_inactive = models.Branch(
            name="B Inactive",
            school_group_id=self.group_b.id,
            status=False,
        )
        self.db.add_all([self.branch_a1, self.branch_a2, self.branch_b1, self.branch_b_inactive])
        self.db.flush()
        self.year_a = models.AcademicYear(
            school_group_id=self.group_a.id,
            year_name="2026-2027",
            is_active=True,
        )
        self.year_b = models.AcademicYear(
            school_group_id=self.group_b.id,
            year_name="2026-2027",
            is_active=True,
        )
        self.db.add_all([self.year_a, self.year_b])
        self.db.flush()

        common = {
            "password": auth.get_password_hash("password123"),
            "is_active": True,
        }
        self.platform_owner = models.User(
            user_id="9001",
            username="owner",
            email="owner@example.com",
            first_name="Platform",
            last_name="Owner",
            user_type=auth.USER_TYPE_PLATFORM,
            platform_role=auth.PLATFORM_ROLE_OWNER,
            platform_owner_kind=auth.PLATFORM_OWNER_PRIMARY,
            access_scope=auth.ACCESS_SCOPE_GLOBAL,
            role=None,
            position=None,
            # Stale tenant fields must never constrain a platform identity.
            school_group_id=self.group_a.id,
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
            **common,
        )
        self.excellence_user = models.User(
            user_id="1001",
            username="excellence",
            first_name="Education",
            last_name="Excellence",
            user_type=auth.USER_TYPE_TENANT,
            platform_role=None,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            role=auth.ROLE_USER,
            position=auth.POSITION_EDUCATION_EXCELLENCE,
            school_group_id=self.group_a.id,
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
            **common,
        )
        self.branch_user = models.User(
            user_id="2001",
            username="branch",
            first_name="Branch",
            last_name="User",
            user_type=auth.USER_TYPE_TENANT,
            platform_role=None,
            access_scope=auth.ACCESS_SCOPE_BRANCH,
            role=auth.ROLE_ADMINISTRATOR,
            position="Principal",
            school_group_id=self.group_a.id,
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
            **common,
        )
        self.tenant_b = models.User(
            user_id="4001",
            username="tenant_b",
            first_name="Beta",
            last_name="Administrator",
            user_type=auth.USER_TYPE_TENANT,
            platform_role=None,
            access_scope=auth.ACCESS_SCOPE_BRANCH,
            role=auth.ROLE_ADMINISTRATOR,
            position="Principal",
            school_group_id=self.group_b.id,
            branch_id=self.branch_b1.id,
            academic_year_id=self.year_b.id,
            **common,
        )
        self.db.add_all(
            [self.platform_owner, self.excellence_user, self.branch_user, self.tenant_b]
        )
        self.db.flush()
        self.teacher_a = models.Teacher(
            teacher_id="5101",
            first_name="Global Alpha",
            last_name="Teacher",
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
        )
        self.teacher_b = models.Teacher(
            teacher_id="5201",
            first_name="Global Beta",
            last_name="Teacher",
            branch_id=self.branch_b1.id,
            academic_year_id=self.year_b.id,
        )
        self.subject_a = models.Subject(
            subject_code="GLA101",
            subject_name="Global Alpha Subject",
            weekly_hours=3,
            grade=1,
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
        )
        self.subject_b = models.Subject(
            subject_code="GLB101",
            subject_name="Global Beta Subject",
            weekly_hours=3,
            grade=1,
            branch_id=self.branch_b1.id,
            academic_year_id=self.year_b.id,
        )
        self.db.add_all([self.teacher_a, self.teacher_b, self.subject_a, self.subject_b])
        self.db.flush()
        self.observation_a = models.Observation(
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
            teacher_id=self.teacher_a.id,
            evaluator_user_id=self.branch_user.user_id,
            observation_date="2026-09-01",
        )
        self.observation_b = models.Observation(
            branch_id=self.branch_b1.id,
            academic_year_id=self.year_b.id,
            teacher_id=self.teacher_b.id,
            evaluator_user_id=self.tenant_b.user_id,
            observation_date="2026-09-02",
        )
        self.db.add_all([self.observation_a, self.observation_b])
        self.db.commit()

    def _request(self, path, user, branch=None, year=None, method="GET", organization=None):
        cookies = [f"{auth.SESSION_COOKIE_KEY}={auth.create_session_token(user)}"]
        if organization:
            cookies.append(f"school_group_id={organization.id}")
        if branch:
            cookies.append(f"branch_id={branch.id}")
        if year:
            cookies.append(f"academic_year_id={year.id}")
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [(b"cookie", "; ".join(cookies).encode("utf-8"))],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
            "app": main.app,
        }
        return Request(scope)

    def test_platform_owner_can_switch_across_organizations(self):
        request = self._request(
            "/platform",
            self.platform_owner,
            self.branch_b1,
            self.year_b,
        )
        current_user = auth.get_current_user(request, self.db)

        self.assertTrue(auth.is_platform_owner(current_user))
        self.assertEqual(auth.get_access_scope(current_user), auth.ACCESS_SCOPE_GLOBAL)
        self.assertEqual(current_user.scope_school_group_id, self.group_b.id)
        self.assertEqual(current_user.scope_branch_id, self.branch_b1.id)
        self.assertEqual(
            {row.id for row in auth.get_accessible_branch_query(self.db, current_user).all()},
            {
                self.branch_a1.id,
                self.branch_a2.id,
                self.branch_b1.id,
                self.branch_b_inactive.id,
            },
        )
        self.assertNotEqual(current_user.scope_branch_id, current_user.branch_id)
        self.assertNotEqual(current_user.scope_school_group_id, current_user.school_group_id)

    def test_platform_owner_has_no_implicit_legacy_context_and_can_select_any_branch(self):
        global_user = auth.get_current_user(
            self._request("/platform", self.platform_owner),
            self.db,
        )
        self.assertIsNone(global_user.scope_branch_id)
        self.assertIsNone(global_user.scope_school_group_id)
        self.assertIsNone(global_user.scope_academic_year_id)
        self.assertIsNone(auth.get_user_school_group_id(self.db, global_user))

        global_recipient_ids = {
            row.user_id
            for row in auth.get_notification_recipient_query(self.db, global_user).all()
        }
        self.assertIn(self.branch_user.user_id, global_recipient_ids)
        self.assertIn(self.tenant_b.user_id, global_recipient_ids)

        users_response = users.users_page(
            request=self._request("/users", self.platform_owner),
            db=self.db,
        )
        users_body = bytes(users_response.body).decode("utf-8")
        self.assertIn("Branch User", users_body)
        self.assertIn("Beta Administrator", users_body)

        response = main.set_scope_branch(
            request=self._request("/scope/branch", self.platform_owner, method="POST"),
            branch_id=self.branch_b1.id,
            return_to="/dashboard",
            db=self.db,
        )
        cookies = b"\n".join(value for key, value in response.raw_headers if key == b"set-cookie")
        self.assertIn(f"branch_id={self.branch_b1.id}".encode("ascii"), cookies)
        self.assertIn(f"academic_year_id={self.year_b.id}".encode("ascii"), cookies)

        inactive_response = main.set_scope_branch(
            request=self._request("/scope/branch", self.platform_owner, method="POST"),
            branch_id=self.branch_b_inactive.id,
            return_to="/dashboard",
            db=self.db,
        )
        inactive_cookies = b"\n".join(
            value for key, value in inactive_response.raw_headers if key == b"set-cookie"
        )
        self.assertIn(
            f"branch_id={self.branch_b_inactive.id}".encode("ascii"),
            inactive_cookies,
        )

    def test_switching_organization_clears_cross_organization_branch_context(self):
        response = main.set_scope_organization(
            request=self._request(
                "/scope/organization",
                self.platform_owner,
                self.branch_a1,
                self.year_a,
                method="POST",
                organization=self.group_a,
            ),
            school_group_id=self.group_b.id,
            return_to="/platform",
            db=self.db,
        )
        cookies = b"\n".join(value for key, value in response.raw_headers if key == b"set-cookie")
        self.assertIn(f"school_group_id={self.group_b.id}".encode("ascii"), cookies)
        self.assertIn(b"branch_id=", cookies)
        self.assertIn(b"academic_year_id=", cookies)

        mismatched_user = auth.get_current_user(
            self._request(
                "/platform",
                self.platform_owner,
                self.branch_a1,
                self.year_a,
                organization=self.group_b,
            ),
            self.db,
        )
        self.assertEqual(mismatched_user.scope_school_group_id, self.group_b.id)
        self.assertIsNone(mismatched_user.scope_branch_id)
        self.assertIsNone(mismatched_user.scope_academic_year_id)

        console_response = main.platform_console(
            request=self._request(
                "/platform",
                self.platform_owner,
                organization=self.group_b,
            ),
            db=self.db,
        )
        body = bytes(console_response.body).decode("utf-8")
        self.assertIn("Workspace UUID", body)
        self.assertIn("Classification", body)
        self.assertIn("Internal Sandbox", body)
        self.assertIn("Lifecycle", body)
        self.assertEqual(body.count("data-organization-card data-search="), 2)
        self.assertEqual(body.count("data-organization-card data-search=\"group b"), 1)
        expanded_organizations = re.findall(
            r'<details class="organization-card"[^>]*\sopen>',
            body,
        )
        self.assertEqual(expanded_organizations, [])

        switched_shell = build_shell_context(
            self._request(
                "/platform",
                self.platform_owner,
                self.branch_a1,
                self.year_a,
                organization=self.group_b,
            ),
            self.db,
            mismatched_user,
            page_key="platform",
        )["shell"]
        self.assertIsNone(switched_shell["scoped_branch_id"])
        self.assertEqual(switched_shell["school_group_id"], self.group_b.id)
        self.assertEqual(
            {branch.id for branch in switched_shell["available_scope_branches"]},
            {self.branch_b1.id, self.branch_b_inactive.id},
        )

        refreshed_user = auth.get_current_user(
            self._request(
                "/platform",
                self.platform_owner,
                organization=self.group_b,
            ),
            self.db,
        )
        refreshed_shell = build_shell_context(
            self._request(
                "/platform",
                self.platform_owner,
                organization=self.group_b,
            ),
            self.db,
            refreshed_user,
            page_key="platform",
        )["shell"]
        self.assertEqual(
            {branch.id for branch in refreshed_shell["available_scope_branches"]},
            {self.branch_b1.id, self.branch_b_inactive.id},
        )

    def test_sidebar_branches_follow_platform_and_tenant_organization_scope(self):
        platform_user = auth.get_current_user(
            self._request(
                "/platform",
                self.platform_owner,
                organization=self.group_a,
            ),
            self.db,
        )
        platform_shell = build_shell_context(
            self._request(
                "/platform",
                self.platform_owner,
                organization=self.group_a,
            ),
            self.db,
            platform_user,
            page_key="platform",
        )["shell"]
        self.assertEqual(
            {branch.id for branch in platform_shell["available_scope_branches"]},
            {self.branch_a1.id, self.branch_a2.id},
        )

        tenant_user = auth.get_current_user(
            self._request(
                "/dashboard",
                self.excellence_user,
                self.branch_a2,
                self.year_a,
                organization=self.group_b,
            ),
            self.db,
        )
        tenant_shell = build_shell_context(
            self._request(
                "/dashboard",
                self.excellence_user,
                self.branch_a2,
                self.year_a,
                organization=self.group_b,
            ),
            self.db,
            tenant_user,
            page_key="dashboard",
        )["shell"]
        self.assertEqual(tenant_shell["school_group_id"], self.group_a.id)
        self.assertEqual(
            {branch.id for branch in tenant_shell["available_scope_branches"]},
            {self.branch_a1.id, self.branch_a2.id},
        )

    def test_academic_year_delete_requires_empty_data_and_matching_organization(self):
        empty_year = models.AcademicYear(
            school_group_id=self.group_a.id,
            year_name="2027-2028",
            is_active=False,
        )
        foreign_empty_year = models.AcademicYear(
            school_group_id=self.group_b.id,
            year_name="2027-2028",
            is_active=False,
        )
        self.db.add_all([empty_year, foreign_empty_year])
        self.db.commit()

        year_rows = {
            row["id"]: row
            for row in main._build_academic_year_configuration_rows(
                self.db,
                self.group_a.id,
            )
        }
        self.assertTrue(year_rows[empty_year.id]["can_delete"])
        self.assertEqual(year_rows[empty_year.id]["linked_records_count"], 0)
        self.assertFalse(year_rows[self.year_a.id]["can_delete"])
        self.assertGreater(year_rows[self.year_a.id]["linked_records_count"], 0)

        blocked_response = main.delete_academic_year(
            academic_year_id=self.year_a.id,
            request=self._request(
                "/system-configuration/academic-years/delete",
                self.platform_owner,
                self.branch_a1,
                self.year_a,
                method="POST",
                organization=self.group_a,
            ),
            return_to=f"/system-configuration/schools?school_group_id={self.group_a.id}",
            db=self.db,
        )
        self.assertEqual(blocked_response.status_code, 302)
        self.assertIn("cannot+be+deleted", blocked_response.headers["location"])
        self.assertIsNotNone(
            self.db.query(models.AcademicYear).filter(
                models.AcademicYear.id == self.year_a.id
            ).first()
        )

        foreign_response = main.delete_academic_year(
            academic_year_id=foreign_empty_year.id,
            request=self._request(
                "/system-configuration/academic-years/delete",
                self.branch_user,
                self.branch_a1,
                self.year_a,
                method="POST",
            ),
            return_to=f"/system-configuration/schools?school_group_id={self.group_b.id}",
            db=self.db,
        )
        self.assertEqual(foreign_response.status_code, 302)
        self.assertEqual(foreign_response.headers["location"], "/dashboard")
        self.assertIsNotNone(
            self.db.query(models.AcademicYear).filter(
                models.AcademicYear.id == foreign_empty_year.id
            ).first()
        )

        deleted_response = main.delete_academic_year(
            academic_year_id=empty_year.id,
            request=self._request(
                "/system-configuration/academic-years/delete",
                self.platform_owner,
                self.branch_a1,
                empty_year,
                method="POST",
                organization=self.group_a,
            ),
            return_to=f"/system-configuration/schools?school_group_id={self.group_a.id}",
            db=self.db,
        )
        self.assertEqual(deleted_response.status_code, 302)
        self.assertIn("notice=Academic+year+deleted+successfully", deleted_response.headers["location"])
        self.assertIsNone(
            self.db.query(models.AcademicYear).filter(
                models.AcademicYear.id == empty_year.id
            ).first()
        )
        deleted_cookies = b"\n".join(
            value for key, value in deleted_response.raw_headers if key == b"set-cookie"
        )
        self.assertIn(b"academic_year_id=", deleted_cookies)

    def test_platform_console_prioritizes_active_data_rich_branches(self):
        empty_branch = models.Branch(
            name="A Empty",
            school_group_id=self.group_a.id,
            status=True,
        )
        data_rich_branch = models.Branch(
            name="Z Data Rich",
            school_group_id=self.group_a.id,
            status=True,
        )
        self.db.add_all([empty_branch, data_rich_branch])
        self.db.flush()
        self.db.add(
            models.Teacher(
                teacher_id="5301",
                first_name="Activity",
                last_name="Signal",
                branch_id=data_rich_branch.id,
                academic_year_id=self.year_a.id,
            )
        )
        self.db.flush()

        console_response = main.platform_console(
            request=self._request("/platform", self.platform_owner),
            db=self.db,
        )
        body = bytes(console_response.body).decode("utf-8")

        self.assertLess(
            body.index(">Z Data Rich</strong>"),
            body.index(">A Empty</strong>"),
        )
        self.assertLess(
            body.index(">B1</strong>"),
            body.index(">B Inactive</strong>"),
        )

        shell = build_shell_context(
            self._request("/platform", self.platform_owner),
            self.db,
            auth.get_current_user(
                self._request("/platform", self.platform_owner),
                self.db,
            ),
            page_key="platform",
        )["shell"]
        nav_icons = {item["label"]: item["icon"] for item in shell["nav_items"]}
        self.assertEqual(nav_icons["Platform Console"], "shield")
        self.assertEqual(nav_icons["System Configuration"], "settings")
        self.assertEqual(shell["page_icon"], "shield")

    def test_tenant_user_cannot_select_platform_organization_context(self):
        response = main.set_scope_organization(
            request=self._request(
                "/scope/organization",
                self.branch_user,
                self.branch_a1,
                self.year_a,
                method="POST",
            ),
            school_group_id=self.group_b.id,
            return_to="/platform",
            db=self.db,
        )
        self.assertEqual(response.status_code, 403)

    def test_platform_owner_selected_context_drives_major_modules(self):
        request = self._request(
            "/dashboard",
            self.platform_owner,
            self.branch_b1,
            self.year_b,
        )
        current_user = auth.get_current_user(request, self.db)

        dashboard_response = main.dashboard(request=request, db=self.db)
        dashboard_body = bytes(dashboard_response.body).decode("utf-8")
        self.assertIn("Global Beta Subject", dashboard_body)
        self.assertNotIn("Global Alpha Subject", dashboard_body)

        teacher_response = teachers.teachers_page(request=request, db=self.db)
        teacher_body = bytes(teacher_response.body).decode("utf-8")
        self.assertIn("Global Beta", teacher_body)
        self.assertNotIn("Global Alpha", teacher_body)

        subject_response = subjects.subjects_page(
            request=request,
            db=self.db,
            current_user=current_user,
        )
        subject_body = bytes(subject_response.body).decode("utf-8")
        self.assertIn("Global Beta Subject", subject_body)
        self.assertNotIn("Global Alpha Subject", subject_body)

        self.assertIsNotNone(
            observations._get_observation_for_current_scope(
                self.db,
                current_user,
                self.observation_b.id,
            )
        )
        self.assertIsNone(
            observations._get_observation_for_current_scope(
                self.db,
                current_user,
                self.observation_a.id,
            )
        )
        self.assertIs(
            users._get_user_for_management(self.db, current_user, self.branch_user.id),
            self.branch_user,
        )

        export_response = subjects.export_subjects_excel(request=request, db=self.db)
        self.assertEqual(export_response.status_code, 200)

    def test_platform_owner_permissions_do_not_bypass_subscription_entitlements(self):
        protected_paths = (
            "/dashboard",
            "/teachers/",
            "/subjects/",
            "/users",
            "/observations/",
            "/system-configuration",
            "/system-configuration/logos",
            "/demo-requests",
            "/platform",
        )
        for path in protected_paths:
            request = self._request(
                path,
                self.platform_owner,
                self.branch_b1,
                self.year_b,
            )
            self.assertIsNone(
                authorization.enforce_route_permission(request, self.db),
                path,
            )

        subscription_gated_request = self._request(
            "/reports/allocation-plan.xlsx",
            self.platform_owner,
            self.branch_b1,
            self.year_b,
        )
        self.assertIsNotNone(
            authorization.enforce_route_permission(subscription_gated_request, self.db)
        )

        design_user, design_denied = main._get_design_control_access(
            self._request(
                "/system-configuration",
                self.platform_owner,
                self.branch_b1,
                self.year_b,
            ),
            self.db,
        )
        self.assertIsNotNone(design_user)
        self.assertIsNone(design_denied)

        branding_context = main._build_school_logo_module_context(
            self._request(
                "/system-configuration/logos",
                self.platform_owner,
                self.branch_b1,
                self.year_b,
            ),
            self.db,
            design_user,
        )
        self.assertEqual(branding_context["selected_school_group"].id, self.group_b.id)

    def test_education_excellence_is_limited_to_its_organization(self):
        same_group = auth.get_current_user(
            self._request("/dashboard", self.excellence_user, self.branch_a2, self.year_a),
            self.db,
        )
        same_group_scope_branch_id = same_group.scope_branch_id
        same_group_accessible_branch_ids = {
            row.id for row in auth.get_accessible_branch_query(self.db, same_group).all()
        }
        cross_group = auth.get_current_user(
            self._request("/dashboard", self.excellence_user, self.branch_b1, self.year_b),
            self.db,
        )

        self.assertEqual(same_group_scope_branch_id, self.branch_a2.id)
        self.assertEqual(cross_group.scope_branch_id, self.branch_a1.id)
        self.assertEqual(same_group_accessible_branch_ids, {self.branch_a1.id, self.branch_a2.id})
        self.assertEqual(same_group.effective_role, auth.ROLE_LIMITED)
        self.assertTrue(auth.has_permission(self.db, same_group, "subjects.view"))
        self.assertFalse(auth.has_permission(self.db, same_group, "subjects.create"))
        self.assertFalse(auth.has_permission(self.db, same_group, "demo_requests.view"))

    def test_limited_role_stays_read_only_despite_permission_override(self):
        self.db.add(
            models.RolePermission(
                school_group_id=self.group_a.id,
                role=auth.ROLE_LIMITED,
                permission_key="subjects.create",
                is_allowed=True,
            )
        )
        self.db.commit()
        current_user = auth.get_current_user(
            self._request("/dashboard", self.excellence_user, self.branch_a1, self.year_a),
            self.db,
        )
        self.assertTrue(auth.has_permission(self.db, current_user, "subjects.view"))
        self.assertFalse(auth.has_permission(self.db, current_user, "subjects.create"))
        self.assertFalse(auth.can_modify_data(current_user))

    def test_protected_position_submissions_are_forced_to_limited_organization_access(self):
        for user_id, position in (
            ("3002", auth.POSITION_EDUCATION_EXCELLENCE),
            ("3003", auth.POSITION_MANAGEMENT),
        ):
            request = self._request(
                "/users",
                self.branch_user,
                self.branch_a1,
                self.year_a,
                method="POST",
            )
            users.create_user(
                request=request,
                user_id=user_id,
                first_name="Central",
                last_name="Manager",
                position=position,
                role=auth.ROLE_ADMINISTRATOR,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                password="password123",
                branch_id=self.branch_a1.id,
                db=self.db,
            )
            created = self.db.query(models.User).filter(models.User.user_id == user_id).one()
            self.assertEqual(created.role, auth.ROLE_LIMITED)
            self.assertEqual(created.access_scope, auth.ACCESS_SCOPE_ORGANIZATION)
            self.assertEqual(
                {row.id for row in auth.get_accessible_branch_query(self.db, created).all()},
                {self.branch_a1.id, self.branch_a2.id},
            )

    def test_branch_user_cannot_switch_within_or_across_organization(self):
        current_user = auth.get_current_user(
            self._request("/dashboard", self.branch_user, self.branch_a2, self.year_a),
            self.db,
        )
        self.assertEqual(current_user.scope_branch_id, self.branch_a1.id)
        self.assertEqual(
            [row.id for row in auth.get_accessible_branch_query(self.db, current_user).all()],
            [self.branch_a1.id],
        )

    def test_platform_roles_are_not_tenant_role_options_or_manageable_targets(self):
        self.assertNotIn(auth.ROLE_DEVELOPER, users.ROLE_CHOICES)
        self.assertNotIn(auth.ROLE_DEVELOPER, permission_registry.MANAGED_ROLES)
        self.branch_user.role = auth.ROLE_DEVELOPER
        self.assertFalse(auth.is_platform_user(self.branch_user))
        self.branch_user.role = auth.ROLE_ADMINISTRATOR
        self.branch_user.permission_keys = frozenset({"users.view", "users.edit_profile"})
        self.assertFalse(auth.can_manage_target_user_account(self.branch_user, self.platform_owner))
        self.assertIn(auth.POSITION_MANAGEMENT, users.POSITIONS)
        self.assertNotIn("Admin", users.POSITIONS)

    def test_owner_account_ui_shows_identity_status_and_blank_new_account_ids(self):
        response = main.platform_console(
            request=self._request("/platform", self.platform_owner),
            db=self.db,
        )
        body = bytes(response.body).decode("utf-8")
        self.assertIn("Owner Account", body)
        self.assertIn('id="account_user_id" value="9001"', body)
        self.assertIn("Unverified", body)
        self.assertIn("Request Verification", body)
        self.assertIn('action="/platform/account/request-email-verification"', body)
        self.assertIn('href="/saas-admin/accounts"', body)
        self.assertIn("Manage SaaS Accounts", body)
        self.assertNotIn('action="/forgot-password"', body)
        verification_button = re.search(
            r'<button[^>]*>Request Verification</button>',
            body,
        )
        self.assertIsNotNone(verification_button)
        self.assertNotIn("disabled", verification_button.group(0))
        self.assertIn('type="submit">Save</button>', body)
        self.assertNotIn("Save Email", body)
        self.assertNotIn("account-identity-mark", body)
        self.assertIn('id="developer_user_id" name="developer_user_id" value=""', body)
        self.assertIn('id="owner_user_id" name="co_owner_user_id" value=""', body)
        self.assertNotIn('id="developer_user_id" name="developer_user_id" value="9001"', body)
        self.assertNotIn('id="owner_user_id" name="co_owner_user_id" value="9001"', body)

    def test_platform_console_counts_only_true_pending_organizations(self):
        account = saas_models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email="owner-lifecycle@example.com",
            email_normalized="owner-lifecycle@example.com",
            status="active",
            onboarding_status="tenant_active",
        )
        self.db.add(account)
        self.db.flush()
        completed = saas_models.PendingOrganization(
            organization_uuid=str(uuid.uuid4()),
            owner_saas_account_id=account.id,
            organization_name="Completed Workspace",
            status="ready_for_checkout",
            onboarding_step="review",
            billing_status="tenant_active",
            payment_status="paid",
        )
        self.db.add(completed)
        self.db.commit()

        completed_only = main.platform_console(
            request=self._request("/platform", self.platform_owner),
            db=self.db,
        )
        completed_body = bytes(completed_only.body).decode("utf-8")
        self.assertIn("<strong>0</strong><span>Pending</span>", completed_body)
        self.assertIn("View Organization Records", completed_body)
        self.assertNotIn("Open Pending Organizations", completed_body)
        self.assertNotIn("Review Pending Organizations", completed_body)
        self.assertNotIn("Completed Workspace", completed_body)

        pending = saas_models.PendingOrganization(
            organization_uuid=str(uuid.uuid4()),
            owner_saas_account_id=account.id,
            organization_name="Pending Workspace",
            status="draft",
            onboarding_step="organization",
            billing_status="not_started",
            payment_status="pending",
        )
        self.db.add(pending)
        self.db.commit()

        with_pending = main.platform_console(
            request=self._request("/platform", self.platform_owner),
            db=self.db,
        )
        pending_body = bytes(with_pending.body).decode("utf-8")
        self.assertIn("<strong>1</strong><span>Pending</span>", pending_body)
        self.assertIn("Review Pending Organizations", pending_body)
        self.assertIn("Pending Workspace", pending_body)
        self.assertNotIn("Completed Workspace", pending_body)

    def test_owner_email_change_requires_password_is_unique_and_resets_verification(self):
        self.platform_owner.email_normalized = auth.normalize_email(self.platform_owner.email)
        self.platform_owner.email_verified_at = datetime.now()
        self.branch_user.email = "used@example.com"
        self.branch_user.email_normalized = auth.normalize_email(self.branch_user.email)
        self.db.commit()

        wrong_password = main.update_platform_owner_email(
            request=self._request("/platform/account/email", self.platform_owner, method="POST"),
            email="new-owner@example.com",
            current_password="wrong-password",
            db=self.db,
        )
        self.assertEqual(wrong_password.status_code, 302)
        self.db.refresh(self.platform_owner)
        self.assertEqual(self.platform_owner.email, "owner@example.com")

        duplicate = main.update_platform_owner_email(
            request=self._request("/platform/account/email", self.platform_owner, method="POST"),
            email=" USED@example.com ",
            current_password="password123",
            db=self.db,
        )
        self.assertEqual(duplicate.status_code, 302)
        self.db.refresh(self.platform_owner)
        self.assertEqual(self.platform_owner.email, "owner@example.com")

        updated = main.update_platform_owner_email(
            request=self._request("/platform/account/email", self.platform_owner, method="POST"),
            email=" New-Owner@Example.com ",
            current_password="password123",
            db=self.db,
        )
        self.assertEqual(updated.status_code, 302)
        self.db.refresh(self.platform_owner)
        self.assertEqual(self.platform_owner.email, "New-Owner@Example.com")
        self.assertEqual(self.platform_owner.email_normalized, "new-owner@example.com")
        self.assertIsNone(self.platform_owner.email_verified_at)
        self.assertEqual(
            auth.authenticate_user(self.db, "NEW-OWNER@example.com", "password123").id,
            self.platform_owner.id,
        )

    def test_owner_verification_request_reports_unconfigured_email_service(self):
        self.platform_owner.email_normalized = auth.normalize_email(self.platform_owner.email)
        self.platform_owner.email_verified_at = None
        self.db.commit()
        local_links = []
        expected_log_path = os.path.normpath(
            os.path.join(os.path.dirname(main.__file__), "logs", "email_verification.log")
        )

        def capture_local_link(user, url):
            local_links.append(url)
            return expected_log_path

        with (
            patch.dict(
                os.environ,
                {"RESEND_API_KEY": "", "TIS_ENV": "local"},
                clear=False,
            ),
            patch.object(
                main,
                "_write_local_email_verification_link",
                side_effect=capture_local_link,
            ),
        ):
            response = main.request_platform_owner_email_verification(
                request=self._request(
                    "/platform/account/request-email-verification",
                    self.platform_owner,
                    method="POST",
                ),
                db=self.db,
        )
        self.assertEqual(response.status_code, 302)
        decoded_location = unquote_plus(response.headers["location"])
        self.assertIn(
            "Email service is not configured. Verification link is available in local logs:",
            decoded_location,
        )
        self.assertIn(expected_log_path, decoded_location)
        self.assertEqual(len(local_links), 1)
        token = parse_qs(urlparse(local_links[0]).query)["token"][0]
        self.assertIsNotNone(auth.decode_email_verification_token(token))
        self.db.refresh(self.platform_owner)
        self.assertIsNone(self.platform_owner.email_verified_at)

    def test_local_verification_writer_creates_folder_and_clear_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = os.path.join(temp_dir, "nested", "email_verification.log")
            verification_url = "http://testserver/platform/account/verify-email?token=signed-token"
            with patch.dict(
                os.environ,
                {"TIS_LOCAL_EMAIL_VERIFICATION_LOG": log_path},
                clear=False,
            ):
                resolved_path = main._write_local_email_verification_link(
                    self.platform_owner,
                    verification_url,
                )

            self.assertEqual(resolved_path, os.path.normpath(os.path.abspath(log_path)))
            self.assertTrue(os.path.isfile(resolved_path))
            with open(resolved_path, "r", encoding="utf-8") as log_file:
                contents = log_file.read()
            self.assertIn("purpose=owner_email_verification", contents)
            self.assertIn(f"verification_url={verification_url}", contents)

    def test_production_never_logs_verification_token_without_resend(self):
        self.platform_owner.email_normalized = auth.normalize_email(self.platform_owner.email)
        self.platform_owner.email_verified_at = None
        self.db.commit()
        with (
            patch.dict(
                os.environ,
                {"RESEND_API_KEY": "", "TIS_ENV": "production"},
                clear=False,
            ),
            patch.object(main, "_write_local_email_verification_link") as local_log,
        ):
            response = main.request_platform_owner_email_verification(
                request=self._request(
                    "/platform/account/request-email-verification",
                    self.platform_owner,
                    method="POST",
                ),
                db=self.db,
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("Email+service+is+not+configured.", response.headers["location"])
        local_log.assert_not_called()

    def test_owner_email_is_verified_only_after_signed_link_confirmation(self):
        self.platform_owner.email_normalized = auth.normalize_email(self.platform_owner.email)
        self.platform_owner.email_verified_at = None
        self.db.commit()
        sent_messages = []
        notification_count = self.db.query(models.SystemNotification).count()

        def capture_email(**message):
            sent_messages.append(message)
            return "resend-message-id"

        with (
            patch.dict(
                os.environ,
                {
                    "RESEND_API_KEY": "re_test_key",
                    "EMAIL_FROM": "info@tisplatform.com",
                    "EMAIL_REPLY_TO": "info@tisplatform.com",
                    "TIS_PUBLIC_BASE_URL": "https://tisplatform.com",
                },
                clear=False,
            ),
            patch.object(main.email_service, "send_email", side_effect=capture_email),
        ):
            response = main.request_platform_owner_email_verification(
                request=self._request(
                    "/platform/account/request-email-verification",
                    self.platform_owner,
                    method="POST",
                ),
                db=self.db,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("verification_sent=1", response.headers["location"])
        self.assertIn("Verification+email+has+been+sent.", response.headers["location"])
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0]["to"], self.platform_owner.email)
        self.assertEqual(
            sent_messages[0]["subject"],
            "Verify your email address | TIS Platform",
        )
        self.assertNotIn("forgot password", sent_messages[0]["text"].casefold())
        self.assertIn("Verify Email", sent_messages[0]["html"])
        self.assertIn("TIS%20Wordmark%20Only", sent_messages[0]["html"])
        self.assertIn("https://tisplatform.com/static/branding/tis/logos/", sent_messages[0]["html"])
        self.assertEqual(self.db.query(models.SystemNotification).count(), notification_count)
        self.db.refresh(self.platform_owner)
        self.assertIsNone(self.platform_owner.email_verified_at)

        sent_state_request = self._request("/platform", self.platform_owner)
        sent_state_request.scope["query_string"] = b"verification_sent=1"
        sent_state = main.platform_console(request=sent_state_request, db=self.db)
        sent_state_body = bytes(sent_state.body).decode("utf-8")
        self.assertIn("Verification Email Sent", sent_state_body)
        self.assertNotIn(">Request Verification</button>", sent_state_body)

        match = re.search(r"https?://\S+", sent_messages[0]["text"])
        self.assertIsNotNone(match)
        token = parse_qs(urlparse(match.group(0)).query)["token"][0]
        confirmed = main.verify_platform_owner_email(token=token, db=self.db)
        self.assertEqual(confirmed.status_code, 302)
        self.db.refresh(self.platform_owner)
        self.assertIsNotNone(self.platform_owner.email_verified_at)

    def test_owner_verification_link_is_rejected_after_email_changes(self):
        self.platform_owner.email_normalized = auth.normalize_email(self.platform_owner.email)
        token = auth.create_email_verification_token(self.platform_owner)
        self.platform_owner.email = "changed@example.com"
        self.platform_owner.email_normalized = auth.normalize_email(self.platform_owner.email)
        self.db.commit()

        response = main.verify_platform_owner_email(token=token, db=self.db)
        self.assertEqual(response.status_code, 400)
        self.db.refresh(self.platform_owner)
        self.assertIsNone(self.platform_owner.email_verified_at)

    def test_forgot_password_keeps_internal_request_and_delivers_via_resend(self):
        sent_messages = []

        def capture_email(**message):
            sent_messages.append(message)
            return "resend-password-message-id"

        request = SimpleNamespace(
            method="POST",
            client=SimpleNamespace(host="testclient"),
            json=AsyncMock(return_value={"user_id": self.branch_user.user_id}),
            form=AsyncMock(return_value={}),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "RESEND_API_KEY": "re_test_key",
                    "EMAIL_FROM": "info@tisplatform.com",
                    "EMAIL_REPLY_TO": "support@tisplatform.com",
                    "TIS_PUBLIC_BASE_URL": "https://tisplatform.com",
                },
                clear=False,
            ),
            patch.object(main.email_service, "send_email", side_effect=capture_email),
        ):
            response = asyncio.run(main.forgot_password(request=request, db=self.db))

        payload = json.loads(bytes(response.body).decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        notification = self.db.query(models.SystemNotification).filter(
            models.SystemNotification.requesting_user_id == self.branch_user.user_id,
            models.SystemNotification.request_type == main.NOTIFICATION_TYPE_FORGOT_PASSWORD,
        ).one()
        self.assertEqual(notification.title, "Forgot Password Request")
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0]["to"], "support@tisplatform.com")
        self.assertEqual(
            sent_messages[0]["subject"],
            "Password reset request | TIS Platform",
        )
        self.assertIn(self.branch_user.user_id, sent_messages[0]["text"])
        self.assertIn("Open TIS Platform", sent_messages[0]["html"])

    def test_forgot_password_resend_failure_is_clear_and_keeps_internal_request(self):
        request = SimpleNamespace(
            method="POST",
            client=SimpleNamespace(host="testclient"),
            json=AsyncMock(return_value={"user_id": self.branch_user.user_id}),
            form=AsyncMock(return_value={}),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "RESEND_API_KEY": "re_test_key",
                    "EMAIL_FROM": "info@tisplatform.com",
                    "EMAIL_REPLY_TO": "support@tisplatform.com",
                    "TIS_PUBLIC_BASE_URL": "https://tisplatform.com",
                },
                clear=False,
            ),
            patch.object(
                main.email_service,
                "send_email",
                side_effect=main.email_service.EmailDeliveryError("provider unavailable"),
            ),
        ):
            response = asyncio.run(main.forgot_password(request=request, db=self.db))

        payload = json.loads(bytes(response.body).decode("utf-8"))
        self.assertEqual(response.status_code, 502)
        self.assertFalse(payload["ok"])
        self.assertIn("request was saved inside TIS", payload["message"])
        self.assertEqual(
            self.db.query(models.SystemNotification).filter(
                models.SystemNotification.requesting_user_id == self.branch_user.user_id,
                models.SystemNotification.request_type == main.NOTIFICATION_TYPE_FORGOT_PASSWORD,
            ).count(),
            1,
        )

    def test_owner_password_change_requires_current_password_and_confirmation(self):
        rejected = main.update_platform_owner_password(
            request=self._request("/platform/account/password", self.platform_owner, method="POST"),
            current_password="wrong-password",
            new_password="new-password-123",
            confirm_password="new-password-123",
            db=self.db,
        )
        self.assertEqual(rejected.status_code, 302)
        self.assertIsNotNone(auth.authenticate_user(self.db, self.platform_owner.user_id, "password123"))

        mismatch = main.update_platform_owner_password(
            request=self._request("/platform/account/password", self.platform_owner, method="POST"),
            current_password="password123",
            new_password="new-password-123",
            confirm_password="different-password-123",
            db=self.db,
        )
        self.assertEqual(mismatch.status_code, 302)
        self.assertIsNotNone(auth.authenticate_user(self.db, self.platform_owner.user_id, "password123"))

        updated = main.update_platform_owner_password(
            request=self._request("/platform/account/password", self.platform_owner, method="POST"),
            current_password="password123",
            new_password="new-password-123",
            confirm_password="new-password-123",
            db=self.db,
        )
        self.assertEqual(updated.status_code, 302)
        self.assertIsNone(auth.authenticate_user(self.db, self.platform_owner.user_id, "password123"))
        self.assertIsNotNone(auth.authenticate_user(self.db, self.platform_owner.user_id, "new-password-123"))

    def test_owner_id_cannot_be_reused_for_new_platform_account(self):
        response = main.create_platform_developer(
            request=self._request("/platform/developers", self.platform_owner, method="POST"),
            user_id=self.platform_owner.user_id,
            username="duplicate.owner.id",
            email="different@example.com",
            first_name="Different",
            last_name="Account",
            password="strongpassword123",
            permission_keys=[],
            db=self.db,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.db.query(models.User).filter(models.User.user_id == self.platform_owner.user_id).count(),
            1,
        )

    def test_owner_account_changes_have_specific_audit_actions(self):
        self.assertEqual(
            audit._classify_action("POST", "/platform/account/email"),
            "Update Platform Owner Email",
        )
        self.assertEqual(
            audit._classify_action("POST", "/platform/account/password"),
            "Change Platform Owner Password",
        )
        self.assertEqual(
            audit._classify_action("POST", "/platform/account/request-email-verification"),
            "Request Platform Owner Email Verification",
        )
        self.assertEqual(
            audit._classify_action("GET", "/platform/account/verify-email"),
            "Verify Platform Owner Email",
        )

    def test_owner_creates_bounded_developer_permissions_and_controls_stay_hidden(self):
        request = self._request(
            "/platform/developers",
            self.platform_owner,
            method="POST",
        )
        response = main.create_platform_developer(
            request=request,
            user_id="9101",
            username="tech.dev",
            email="tech@example.com",
            first_name="Technical",
            last_name="Developer",
            password="strongpassword123",
            permission_keys=[
                "subjects.view",
                "design_control.manage",
                "system_owner.transfer_ownership",
                "system_owner.manage_developer_accounts",
            ],
            db=self.db,
        )
        self.assertEqual(response.status_code, 302)
        developer = self.db.query(models.User).filter(models.User.user_id == "9101").one()
        self.assertTrue(auth.is_platform_developer(developer))
        self.assertTrue(developer.platform_permissions_initialized)

        developer_request = self._request(
            "/platform",
            developer,
            self.branch_b1,
            self.year_b,
            organization=self.group_b,
        )
        current_developer = auth.get_current_user(developer_request, self.db)
        self.assertTrue(auth.has_permission(self.db, current_developer, "subjects.view"))
        self.assertTrue(auth.has_permission(self.db, current_developer, "design_control.manage"))
        self.assertFalse(
            auth.has_permission(self.db, current_developer, "system_owner.transfer_ownership")
        )
        self.assertFalse(
            auth.has_permission(self.db, current_developer, "system_owner.manage_developer_accounts")
        )

        console = main.platform_console(request=developer_request, db=self.db)
        console_body = bytes(console.body).decode("utf-8")
        self.assertNotIn("Ownership Management", console_body)
        self.assertNotIn("Create Platform Developer", console_body)
        self.assertNotIn("Workspace UUID", console_body)

        denied = main.create_platform_co_owner(
            request=self._request(
                "/platform/owners",
                developer,
                method="POST",
            ),
            user_id="9201",
            username="forbidden.owner",
            email="forbidden@example.com",
            first_name="Forbidden",
            last_name="Owner",
            password="strongpassword123",
            db=self.db,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertIsNone(self.db.query(models.User).filter(models.User.user_id == "9201").first())

    def test_owner_can_add_co_owner_and_transfer_primary_ownership_safely(self):
        create_response = main.create_platform_co_owner(
            request=self._request(
                "/platform/owners",
                self.platform_owner,
                method="POST",
            ),
            user_id="9301",
            username="co.owner",
            email="coowner@example.com",
            first_name="Co",
            last_name="Owner",
            password="strongpassword123",
            db=self.db,
        )
        self.assertEqual(create_response.status_code, 302)
        co_owner = self.db.query(models.User).filter(models.User.user_id == "9301").one()
        self.assertTrue(auth.is_platform_owner(co_owner))
        self.assertEqual(co_owner.platform_owner_kind, auth.PLATFORM_OWNER_CO_OWNER)

        rejected = main.transfer_platform_ownership(
            request=self._request(
                "/platform/ownership/transfer",
                self.platform_owner,
                method="POST",
            ),
            target_user_id=co_owner.user_id,
            current_password="password123",
            confirmation="transfer ownership",
            db=self.db,
        )
        self.assertEqual(rejected.status_code, 302)
        self.db.refresh(co_owner)
        self.assertEqual(co_owner.platform_owner_kind, auth.PLATFORM_OWNER_CO_OWNER)

        transferred = main.transfer_platform_ownership(
            request=self._request(
                "/platform/ownership/transfer",
                self.platform_owner,
                method="POST",
            ),
            target_user_id=co_owner.user_id,
            current_password="password123",
            confirmation="TRANSFER OWNERSHIP",
            db=self.db,
        )
        self.assertEqual(transferred.status_code, 302)
        self.db.refresh(self.platform_owner)
        self.db.refresh(co_owner)
        self.assertEqual(self.platform_owner.platform_owner_kind, auth.PLATFORM_OWNER_CO_OWNER)
        self.assertEqual(co_owner.platform_owner_kind, auth.PLATFORM_OWNER_PRIMARY)
        self.assertTrue(auth.is_primary_platform_owner(co_owner))

    def test_owner_inherits_every_registered_permission(self):
        current_owner = auth.get_current_user(
            self._request("/platform", self.platform_owner),
            self.db,
        )
        self.assertEqual(
            auth.get_allowed_permission_keys(self.db, current_owner),
            set(permission_registry.ALL_PERMISSION_KEYS),
        )

    def test_platform_only_features_are_hidden_from_tenant_users(self):
        request = self._request(
            "/dashboard",
            self.excellence_user,
            self.branch_a1,
            self.year_a,
        )
        current_user = auth.get_current_user(request, self.db)
        shell_context = build_shell_context(
            request,
            self.db,
            current_user,
            page_key="dashboard",
        )
        nav_labels = {item["label"] for item in shell_context["shell"]["nav_items"]}
        self.assertNotIn("Platform Console", nav_labels)
        self.assertNotIn("Demo Requests", nav_labels)
        denied = main.platform_console(request=request, db=self.db)
        self.assertEqual(denied.status_code, 403)

    def test_knowledge_center_remains_owner_only_with_protected_page_links(self):
        owner_response = main.platform_knowledge_center(
            request=self._request("/platform/knowledge", self.platform_owner),
            db=self.db,
        )
        owner_body = bytes(owner_response.body).decode("utf-8")
        self.assertEqual(owner_response.status_code, 200)
        self.assertIn('id="knowledgeSearch"', owner_body)
        self.assertIn("/platform/knowledge/booklet#page=", owner_body)
        self.assertNotIn("/static/docs/TIS_Project_Reference_Booklet.pdf", owner_body)

        denied = main.platform_knowledge_center(
            request=self._request(
                "/platform/knowledge",
                self.excellence_user,
                self.branch_a1,
                self.year_a,
            ),
            db=self.db,
        )
        self.assertEqual(denied.status_code, 403)

    def test_tenant_create_endpoint_rejects_platform_role_and_global_scope(self):
        request = self._request(
            "/users",
            self.branch_user,
            self.branch_a1,
            self.year_a,
            method="POST",
        )
        for index, forbidden_role in enumerate(
            ("Owner", auth.ROLE_DEVELOPER, auth.PLATFORM_ROLE_OWNER, auth.PLATFORM_ROLE_DEVELOPER),
            start=1,
        ):
            user_id = f"31{index:02d}"
            users.create_user(
                request=request,
                user_id=user_id,
                first_name="Invalid",
                last_name="Platform",
                position="Teacher",
                role=forbidden_role,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                password="password123",
                branch_id=self.branch_a1.id,
                db=self.db,
            )
            self.assertIsNone(self.db.query(models.User).filter(models.User.user_id == user_id).first())

    def test_platform_login_redirects_to_console(self):
        self.db.query(models.Branch).update({models.Branch.status: False})
        self.db.query(models.AcademicYear).update({models.AcademicYear.is_active: False})
        self.db.commit()
        request = self._request("/login", self.platform_owner, method="POST")
        response = main.login(
            request=request,
            username=self.platform_owner.user_id,
            password="password123",
            db=self.db,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/platform")
        console_response = main.platform_console(
            request=self._request("/platform", self.platform_owner),
            db=self.db,
        )
        self.assertEqual(console_response.status_code, 200)
        self.assertIn("Platform Console", bytes(console_response.body).decode("utf-8"))

    def test_platform_identity_does_not_trigger_tenant_integrity_errors(self):
        issue_keys = {item["key"] for item in tenant_integrity.collect_tenant_integrity_issues(self.db)}
        self.assertNotIn("users_missing_school_group", issue_keys)
        self.assertNotIn("users_missing_branch", issue_keys)
        self.assertNotIn("users_missing_academic_year", issue_keys)

    def test_legacy_developer_migrates_to_platform_identity(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE school_groups (id INTEGER PRIMARY KEY)"))
                connection.execute(text("INSERT INTO school_groups (id) VALUES (1)"))
                connection.execute(
                    text(
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, role VARCHAR, position VARCHAR, "
                        "school_group_id INTEGER, branch_id INTEGER, academic_year_id INTEGER)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO users (id, role, position, school_group_id, branch_id, academic_year_id) "
                        "VALUES (1, 'Developer', 'Developer', 1, 2, 3), "
                        "(2, 'Administrator', 'Education Excellence', 1, 2, 3), "
                        "(5, 'Editor', 'Management', 1, 2, 3)"
                    )
                )
                db_migrations._platform_identity_and_access_scope(engine, connection)
                db_migrations._sqlite_platform_user_scope_trigger(engine, connection)
                db_migrations._platform_hierarchy_and_permissions(engine, connection)
                rows = connection.execute(
                    text(
                        "SELECT id, user_type, platform_role, access_scope, role, position, branch_id "
                        "FROM users ORDER BY id"
                    )
                ).mappings().all()
            self.assertEqual(rows[0]["user_type"], auth.USER_TYPE_PLATFORM)
            self.assertEqual(rows[0]["platform_role"], auth.PLATFORM_ROLE_DEVELOPER)
            self.assertEqual(rows[0]["access_scope"], auth.ACCESS_SCOPE_GLOBAL)
            self.assertIsNone(rows[0]["role"])
            self.assertIsNone(rows[0]["branch_id"])
            self.assertEqual(rows[1]["user_type"], auth.USER_TYPE_TENANT)
            self.assertEqual(rows[1]["access_scope"], auth.ACCESS_SCOPE_ORGANIZATION)
            self.assertEqual(rows[1]["role"], auth.ROLE_LIMITED)
            self.assertEqual(rows[2]["access_scope"], auth.ACCESS_SCOPE_ORGANIZATION)
            self.assertEqual(rows[2]["role"], auth.ROLE_LIMITED)
            with engine.begin() as connection:
                user_columns = {
                    row[1]
                    for row in connection.execute(text("PRAGMA table_info(users)")).all()
                }
                permissions_table = connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'platform_user_permissions'"
                    )
                ).scalar()
            self.assertIn("email", user_columns)
            self.assertIn("platform_owner_kind", user_columns)
            self.assertIn("platform_permissions_initialized", user_columns)
            self.assertEqual(permissions_table, "platform_user_permissions")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users (id, user_type, platform_role, access_scope) "
                        "VALUES (3, 'PLATFORM', 'Platform Owner', 'GLOBAL')"
                    )
                )
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO users (id, user_type, role, access_scope) "
                            "VALUES (4, 'TENANT', 'User', 'BRANCH')"
                        )
                    )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
