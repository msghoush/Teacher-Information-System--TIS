import json
import os
import unittest

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import auth
import location_service
import main
import models
from routers import academic_calendar


class SaveAllChangesTests(unittest.TestCase):
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

        self.branch_a1 = models.Branch(
            name="A1",
            school_group_id=self.group_a.id,
            status=True,
        )
        self.branch_a2 = models.Branch(
            name="A2",
            school_group_id=self.group_a.id,
            status=True,
        )
        self.branch_b1 = models.Branch(
            name="B1",
            school_group_id=self.group_b.id,
            status=True,
        )
        self.db.add_all([self.branch_a1, self.branch_a2, self.branch_b1])
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
        self.owner = models.User(
            user_id="9001",
            username="owner",
            first_name="Platform",
            last_name="Owner",
            user_type=auth.USER_TYPE_PLATFORM,
            platform_role=auth.PLATFORM_ROLE_OWNER,
            platform_owner_kind=auth.PLATFORM_OWNER_PRIMARY,
            access_scope=auth.ACCESS_SCOPE_GLOBAL,
            **common,
        )
        self.organization_admin = models.User(
            user_id="1001",
            username="org_admin",
            first_name="Organization",
            last_name="Admin",
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            role=auth.ROLE_ADMINISTRATOR,
            position="Principal",
            school_group_id=self.group_a.id,
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
            **common,
        )
        self.db.add_all([self.owner, self.organization_admin])

        self.event_type_a1 = models.CalendarEventType(
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
            name="Assessment",
            color="#0A4EA3",
            icon="calendar",
            is_active=True,
            sort_order=1,
        )
        self.event_type_a2 = models.CalendarEventType(
            branch_id=self.branch_a1.id,
            academic_year_id=self.year_a.id,
            name="Meeting",
            color="#027A48",
            icon="info",
            is_active=True,
            sort_order=2,
        )
        self.event_type_b = models.CalendarEventType(
            branch_id=self.branch_b1.id,
            academic_year_id=self.year_b.id,
            name="Other Scope",
            color="#B42318",
            icon="info",
            is_active=True,
            sort_order=1,
        )
        self.db.add_all([self.event_type_a1, self.event_type_a2, self.event_type_b])

        self.demo_a = models.DemoRequest(
            school_name="Demo A",
            full_name="Contact A",
            email="a@example.test",
            status="New",
        )
        self.demo_b = models.DemoRequest(
            school_name="Demo B",
            full_name="Contact B",
            email="b@example.test",
            status="New",
        )
        self.db.add_all([self.demo_a, self.demo_b])
        self.db.commit()

    def _request(self, path, user, *, branch=None, year=None, organization=None, method="POST"):
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

    @staticmethod
    def _json(response):
        return json.loads(bytes(response.body).decode("utf-8"))

    def test_branch_batch_saves_only_submitted_rows(self):
        response = main.bulk_update_branches(
            request=self._request(
                "/system-configuration/branches/bulk-update",
                self.owner,
                branch=self.branch_a1,
                year=self.year_a,
                organization=self.group_a,
            ),
            payload={
                "items": [
                    {
                        "id": self.branch_a1.id,
                        "name": "A1 Updated",
                        "_changed_fields": ["name"],
                    },
                    {
                        "id": self.branch_a2.id,
                        "status": "inactive",
                        "_changed_fields": ["status"],
                    },
                ]
            },
            db=self.db,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._json(response)["saved_count"], 2)
        self.db.refresh(self.branch_a1)
        self.db.refresh(self.branch_a2)
        self.db.refresh(self.branch_b1)
        self.assertEqual(self.branch_a1.name, "A1 Updated")
        self.assertFalse(self.branch_a2.status)
        self.assertEqual(self.branch_b1.name, "B1")

    def test_branch_batch_updates_multiple_locations_together(self):
        saudi_regions = location_service.list_regions("SA")
        makkah = next(region for region in saudi_regions if region["name"] == "Makkah")
        jeddah = next(
            city
            for city in location_service.list_cities("SA", makkah["id"])
            if city["name"] == "Jeddah"
        )
        us_regions = location_service.list_regions("US")
        california = next(region for region in us_regions if region["name"] == "California")
        san_francisco = next(
            city
            for city in location_service.list_cities("US", california["id"])
            if city["name"] == "San Francisco"
        )

        response = main.bulk_update_branches(
            request=self._request(
                "/system-configuration/branches/bulk-update",
                self.owner,
                branch=self.branch_a1,
                year=self.year_a,
                organization=self.group_a,
            ),
            payload={
                "items": [
                    {
                        "id": self.branch_a1.id,
                        "country_code": "SA",
                        "region_id": str(makkah["id"]),
                        "city_id": str(jeddah["id"]),
                        "district_name": "Central District",
                        "neighborhood_name": "Garden Quarter",
                        "_changed_fields": [
                            "country_code",
                            "region_id",
                            "city_id",
                            "district_name",
                            "neighborhood_name",
                        ],
                    },
                    {
                        "id": self.branch_a2.id,
                        "country_code": "US",
                        "region_id": str(california["id"]),
                        "city_id": str(san_francisco["id"]),
                        "_changed_fields": ["country_code", "region_id", "city_id"],
                    },
                ]
            },
            db=self.db,
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(self.branch_a1)
        self.db.refresh(self.branch_a2)
        self.assertEqual(
            (self.branch_a1.country_code, self.branch_a1.region_name, self.branch_a1.city_name),
            ("SA", "Makkah", "Jeddah"),
        )
        self.assertEqual(self.branch_a1.district_name, "Central District")
        self.assertEqual(self.branch_a1.neighborhood_name, "Garden Quarter")
        self.assertEqual(
            (self.branch_a2.country_code, self.branch_a2.region_name, self.branch_a2.city_name),
            ("US", "California", "San Francisco"),
        )

    def test_organization_location_details_are_saved_without_a_locality_registry(self):
        lebanon_regions = location_service.list_regions("LB")
        beqaa = next(region for region in lebanon_regions if region["name"] == "Beqaa")
        response = main.update_school_group(
            school_group_id=self.group_a.id,
            request=self._request(
                "/system-configuration/schools/1",
                self.owner,
                branch=self.branch_a1,
                year=self.year_a,
                organization=self.group_a,
            ),
            name=self.group_a.name,
            status="active",
            country_code="LB",
            region_id=str(beqaa["id"]),
            region_manual="",
            city_id=location_service.OTHER_VALUE,
            city_manual="Chtaura",
            district_name="Zahle District",
            neighborhood_name="School Quarter",
            return_to=f"/system-configuration/schools?school_group_id={self.group_a.id}",
            db=self.db,
        )

        self.assertEqual(response.status_code, 302)
        self.db.refresh(self.group_a)
        self.assertEqual(
            (
                self.group_a.country_code,
                self.group_a.region_name,
                self.group_a.city_name,
                self.group_a.district_name,
                self.group_a.neighborhood_name,
            ),
            ("LB", "Beqaa", "Chtaura", "Zahle District", "School Quarter"),
        )

    def test_branch_batch_is_atomic_and_preserves_tenant_isolation(self):
        atomic_response = main.bulk_update_branches(
            request=self._request(
                "/system-configuration/branches/bulk-update",
                self.owner,
                branch=self.branch_a1,
                year=self.year_a,
                organization=self.group_a,
            ),
            payload={
                "items": [
                    {"id": self.branch_a1.id, "name": "Duplicate", "_changed_fields": ["name"]},
                    {"id": self.branch_a2.id, "name": "Duplicate", "_changed_fields": ["name"]},
                ]
            },
            db=self.db,
        )
        self.assertEqual(atomic_response.status_code, 422)
        self.db.refresh(self.branch_a1)
        self.db.refresh(self.branch_a2)
        self.assertEqual(self.branch_a1.name, "A1")
        self.assertEqual(self.branch_a2.name, "A2")

        isolation_response = main.bulk_update_branches(
            request=self._request(
                "/system-configuration/branches/bulk-update",
                self.organization_admin,
                branch=self.branch_a1,
                year=self.year_a,
                organization=self.group_a,
            ),
            payload={
                "items": [
                    {"id": self.branch_b1.id, "name": "Cross Tenant", "_changed_fields": ["name"]}
                ]
            },
            db=self.db,
        )
        self.assertEqual(isolation_response.status_code, 422)
        self.assertIn("outside your accessible scope", self._json(isolation_response)["errors"][0]["message"])
        self.db.refresh(self.branch_b1)
        self.assertEqual(self.branch_b1.name, "B1")

    def test_calendar_event_type_batch_is_scope_bound_and_atomic(self):
        duplicate_response = academic_calendar.bulk_update_calendar_event_types(
            request=self._request(
                "/system-configuration/calendar/event-types/bulk/update",
                self.owner,
                branch=self.branch_a1,
                year=self.year_a,
                organization=self.group_a,
            ),
            payload={
                "items": [
                    {
                        "id": self.event_type_a1.id,
                        "name": "Same Name",
                        "color": "#111111",
                        "icon": "calendar",
                        "sort_order": "1",
                        "is_active": True,
                    },
                    {
                        "id": self.event_type_a2.id,
                        "name": "Same Name",
                        "color": "#222222",
                        "icon": "info",
                        "sort_order": "2",
                        "is_active": False,
                    },
                ]
            },
            db=self.db,
        )
        self.assertEqual(duplicate_response.status_code, 422)
        self.db.refresh(self.event_type_a1)
        self.db.refresh(self.event_type_a2)
        self.assertEqual(self.event_type_a1.name, "Assessment")
        self.assertTrue(self.event_type_a2.is_active)

        scope_response = academic_calendar.bulk_update_calendar_event_types(
            request=self._request(
                "/system-configuration/calendar/event-types/bulk/update",
                self.owner,
                branch=self.branch_a1,
                year=self.year_a,
                organization=self.group_a,
            ),
            payload={
                "items": [
                    {
                        "id": self.event_type_b.id,
                        "name": "Wrong Scope",
                        "color": "#333333",
                        "icon": "info",
                        "sort_order": "3",
                        "is_active": True,
                    }
                ]
            },
            db=self.db,
        )
        self.assertEqual(scope_response.status_code, 422)
        self.db.refresh(self.event_type_b)
        self.assertEqual(self.event_type_b.name, "Other Scope")

    def test_demo_request_status_batch_is_atomic(self):
        invalid_response = main.bulk_update_demo_request_statuses(
            request=self._request("/demo-requests/bulk-status", self.owner),
            payload={
                "items": [
                    {"id": self.demo_a.id, "status": "Contacted"},
                    {"id": self.demo_b.id, "status": "Invalid Status"},
                ]
            },
            db=self.db,
        )
        self.assertEqual(invalid_response.status_code, 422)
        self.db.refresh(self.demo_a)
        self.db.refresh(self.demo_b)
        self.assertEqual(self.demo_a.status, "New")
        self.assertEqual(self.demo_b.status, "New")

        saved_response = main.bulk_update_demo_request_statuses(
            request=self._request("/demo-requests/bulk-status", self.owner),
            payload={
                "items": [
                    {"id": self.demo_a.id, "status": "Contacted"},
                    {"id": self.demo_b.id, "status": "Demo Scheduled"},
                ]
            },
            db=self.db,
        )
        self.assertEqual(saved_response.status_code, 200)
        self.db.refresh(self.demo_a)
        self.db.refresh(self.demo_b)
        self.assertEqual(self.demo_a.status, "Contacted")
        self.assertEqual(self.demo_b.status, "Demo Scheduled")

    def test_save_all_controls_render_on_approved_pages(self):
        scoped_request_args = {
            "user": self.owner,
            "branch": self.branch_a1,
            "year": self.year_a,
            "organization": self.group_a,
            "method": "GET",
        }
        schools_response = main.system_configuration_schools(
            request=self._request("/system-configuration/schools", **scoped_request_args),
            db=self.db,
        )
        calendar_response = academic_calendar.system_configuration_calendar(
            request=self._request("/system-configuration/calendar", **scoped_request_args),
            db=self.db,
        )
        demos_response = main.list_demo_requests(
            request=self._request("/demo-requests", self.owner, method="GET"),
            db=self.db,
        )

        for response in (schools_response, calendar_response, demos_response):
            body = bytes(response.body).decode("utf-8")
            self.assertIn("Save All Changes", body)
            self.assertIn("/static/js/save-all-changes.js", body)
        schools_body = bytes(schools_response.body).decode("utf-8")
        self.assertIn("District", schools_body)
        self.assertIn("Neighborhood", schools_body)
        self.assertIn("Other / manual entry", schools_body)


if __name__ == "__main__":
    unittest.main()
