import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import auth
import db_migrations
import models


class IdentityResolverTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.password = "strong-password"
        self.user = models.User(
            user_id="2623252018",
            username="legacy.owner",
            email="Owner@Example.com",
            email_normalized=auth.normalize_email("Owner@Example.com"),
            password=auth.get_password_hash(self.password),
            user_type=auth.USER_TYPE_PLATFORM,
            platform_role=auth.PLATFORM_ROLE_OWNER,
            access_scope=auth.ACCESS_SCOPE_GLOBAL,
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_existing_ten_digit_user_id_login_still_works(self):
        authenticated = auth.authenticate_user(self.db, "2623252018", self.password)
        self.assertEqual(authenticated.id, self.user.id)

    def test_email_login_uses_normalized_email(self):
        authenticated = auth.authenticate_user(
            self.db,
            "  OWNER@example.COM  ",
            self.password,
        )
        self.assertEqual(authenticated.id, self.user.id)

    def test_legacy_username_fallback_still_works(self):
        authenticated = auth.authenticate_user(self.db, "legacy.owner", self.password)
        self.assertEqual(authenticated.id, self.user.id)

    def test_all_identifiers_resolve_to_same_user(self):
        resolved_ids = {
            auth.resolve_login_user(self.db, identifier).id
            for identifier in ("2623252018", "owner@example.com", "legacy.owner")
        }
        self.assertEqual(resolved_ids, {self.user.id})

    def test_duplicate_normalized_email_is_rejected(self):
        duplicate = models.User(
            user_id="1000000001",
            username="another.user",
            email=" owner@example.com ",
            email_normalized=auth.normalize_email(" owner@example.com "),
            password=auth.get_password_hash(self.password),
        )
        self.db.add(duplicate)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_registration_helper_returns_shared_conflict_message(self):
        error = auth.get_email_registration_error(
            self.db,
            "  OWNER@example.com ",
        )
        self.assertEqual(error, auth.EMAIL_ALREADY_REGISTERED_MESSAGE)
        self.assertEqual(
            error,
            "This email is already registered on TIS Platform. Please sign in instead.",
        )
        self.assertFalse(
            auth.is_email_available_for_registration(self.db, "owner@example.com")
        )

    def test_registration_helper_can_exclude_current_account(self):
        self.assertTrue(
            auth.is_email_available_for_registration(
                self.db,
                "OWNER@example.com",
                exclude_user_pk=self.user.id,
            )
        )


class IdentityMigrationTests(unittest.TestCase):
    @staticmethod
    def _legacy_engine():
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        user_id VARCHAR(10),
                        email VARCHAR(180)
                    )
                    """
                )
            )
        return engine

    def test_migration_normalizes_email_and_converts_blank_to_null(self):
        engine = self._legacy_engine()
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO users (id, user_id, email)
                        VALUES (1, '1000000001', ' Person@Example.COM '),
                               (2, '1000000002', '   ')
                        """
                    )
                )
                db_migrations._identity_foundation(engine, connection)

            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT id, email, email_normalized, created_at, updated_at
                        FROM users ORDER BY id
                        """
                    )
                ).mappings().all()
            self.assertEqual(rows[0]["email_normalized"], "person@example.com")
            self.assertIsNotNone(rows[0]["created_at"])
            self.assertIsNotNone(rows[0]["updated_at"])
            self.assertIsNone(rows[1]["email"])
            self.assertIn(
                "uq_users_email_normalized",
                {index["name"] for index in inspect(engine).get_indexes("users")},
            )
        finally:
            engine.dispose()

    def test_migration_stops_before_schema_changes_when_collisions_exist(self):
        engine = self._legacy_engine()
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO users (id, user_id, email)
                        VALUES (1, '1000000001', 'Person@Example.com'),
                               (2, '1000000002', ' person@example.COM ')
                        """
                    )
                )

            with self.assertRaisesRegex(
                RuntimeError,
                "person@example.com: 1000000001, 1000000002",
            ):
                with engine.begin() as connection:
                    db_migrations._identity_foundation(engine, connection)

            columns = {column["name"] for column in inspect(engine).get_columns("users")}
            self.assertNotIn("email_normalized", columns)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
