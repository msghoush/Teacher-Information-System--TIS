import unittest

from sqlalchemy import create_engine, inspect, text

import db_migrations
import location_service


class LocationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location_service.get_location_index.cache_clear()
        cls.index = location_service.get_location_index()

    def test_dataset_is_loaded_once_and_contains_global_countries(self):
        self.assertGreaterEqual(len(self.index.countries), 240)
        self.assertIn("SA", self.index.countries_by_code)
        self.assertIn("US", self.index.countries_by_code)
        self.assertIs(self.index, location_service.get_location_index())
        self.assertEqual(location_service.get_location_index.cache_info().misses, 1)

    def test_regions_and_cities_are_scoped_to_the_parent_selection(self):
        saudi_regions = location_service.list_regions("SA")
        makkah = next(region for region in saudi_regions if region["name"] == "Makkah")
        makkah_cities = location_service.list_cities("SA", makkah["id"])

        self.assertIn("Jeddah", {city["name"] for city in makkah_cities})
        with self.assertRaises(location_service.LocationValidationError):
            location_service.list_cities("US", makkah["id"])

    def test_resolve_location_validates_hierarchy_and_supports_manual_values(self):
        resolved = location_service.resolve_location(
            country_code="SA",
            region_id=location_service.OTHER_VALUE,
            region_manual="Custom Province",
            city_id=location_service.OTHER_VALUE,
            city_manual="Custom City",
        )
        self.assertEqual(resolved.country_name, "Saudi Arabia")
        self.assertEqual(resolved.region_name, "Custom Province")
        self.assertEqual(resolved.city_name, "Custom City")

        with self.assertRaises(location_service.LocationValidationError):
            location_service.resolve_location(
                country_code="SA",
                region_id=location_service.OTHER_VALUE,
                region_manual="Custom Province",
                city_id=location_service.OTHER_VALUE,
                city_manual="x" * 161,
            )

    def test_legacy_saudi_region_remains_valid(self):
        resolved = location_service.infer_legacy_saudi_location("Makkah Region")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.country_code, "SA")
        self.assertEqual(resolved.region_name, "Makkah")


class GlobalLocationMigrationTests(unittest.TestCase):
    def test_migration_adds_columns_and_backfills_legacy_saudi_branch(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE school_groups (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(160) NOT NULL,
                        status BOOLEAN NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE branches (
                        id INTEGER PRIMARY KEY,
                        school_group_id INTEGER,
                        name VARCHAR(160) NOT NULL,
                        location VARCHAR(160),
                        status BOOLEAN
                    )
                    """
                )
            )
            connection.execute(
                text("INSERT INTO school_groups (id, name, status) VALUES (1, 'Al-Andalus', 1)")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO branches (id, school_group_id, name, location, status)
                    VALUES (1, 1, 'Hamdan', 'Makkah Region', 1)
                    """
                )
            )
            db_migrations._global_location_columns(engine, connection)
            db_migrations._phase1_address_detail_columns(engine, connection)

        branch_columns = {column["name"] for column in inspect(engine).get_columns("branches")}
        self.assertTrue(
            {
                "country_code",
                "country_name",
                "region_name",
                "city_name",
                "district_name",
                "neighborhood_name",
            }.issubset(
                branch_columns
            )
        )
        school_columns = {
            column["name"] for column in inspect(engine).get_columns("school_groups")
        }
        self.assertTrue(
            {"district_name", "neighborhood_name"}.issubset(school_columns)
        )
        with engine.connect() as connection:
            branch = connection.execute(
                text(
                    """
                    SELECT country_code, country_name, region_name
                    FROM branches WHERE id = 1
                    """
                )
            ).one()
            school = connection.execute(
                text("SELECT country_code, country_name FROM school_groups WHERE id = 1")
            ).one()
        self.assertEqual(tuple(branch), ("SA", "Saudi Arabia", "Makkah Region"))
        self.assertEqual(tuple(school), ("SA", "Saudi Arabia"))
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
