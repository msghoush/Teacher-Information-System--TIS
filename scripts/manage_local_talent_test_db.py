"""Manage an isolated LOCAL-ONLY Talent & Potential test database.

This script NEVER imports or binds to the application's configured
``database.engine``/``DATABASE_URL``. It builds its own dedicated SQLAlchemy
engine bound to a file strictly inside ``.local_test_data/`` (never ``tis.db``,
never any other tracked repository database file), so schema creation, seeding,
and destructive reset can never reach the Owner's real database no matter what
the process environment happens to have configured for the main application.

Layered safety gate for the destructive ``reset``/``reseed`` commands (never a
single filename-only check):
  1. Refuses outright if auth.is_production_environment() reports a
     production-like TIS_ENV/ENV/FASTAPI_ENV value.
  2. The resolved absolute target path must live inside the dedicated
     .local_test_data/ directory, and must not equal any known tracked
     repository database file (tis.db, tis_backup_before_platform_access_test.db).
  3. The target database must already contain this tool's own sentinel marker
     row (written only by this script's own ``create``/``seed`` commands) -
     proving the file was actually created by this tool, not merely guessed to
     be safe by name or path.
  4. The caller must pass --confirm on the command line for reset/reseed.

Usage:
  python scripts/manage_local_talent_test_db.py create
  python scripts/manage_local_talent_test_db.py seed
  python scripts/manage_local_talent_test_db.py status
  python scripts/manage_local_talent_test_db.py reset --confirm
  python scripts/manage_local_talent_test_db.py reseed --confirm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

import auth
import models  # noqa: F401 - registers ORM metadata on database.Base
import saas.models  # noqa: F401 - registers SaaS ORM metadata on the same Base
from database import Base

LOCAL_TEST_DIR = ROOT / ".local_test_data"
DEFAULT_DB_PATH = LOCAL_TEST_DIR / "talent_local_test.db"

# Tracked repository database files this tool must never resolve to, by design -
# not the only safety layer, but always checked in addition to the others.
FORBIDDEN_ABSOLUTE_PATHS = {
    (ROOT / "tis.db").resolve(),
    (ROOT / "tis_backup_before_platform_access_test.db").resolve(),
}

MARKER_TABLE = "local_test_environment_marker"
MARKER_VALUE = "tis-talent-local-test-db-v1"


class LocalTestDatabaseSafetyError(RuntimeError):
    pass


def resolve_target_path() -> Path:
    return DEFAULT_DB_PATH


def _assert_safe_target(path: Path) -> None:
    if auth.is_production_environment():
        raise LocalTestDatabaseSafetyError(
            "Refusing: TIS_ENV/ENV/FASTAPI_ENV indicates a production-like environment."
        )
    resolved = path.resolve()
    try:
        resolved.relative_to(LOCAL_TEST_DIR.resolve())
    except ValueError:
        raise LocalTestDatabaseSafetyError(
            f"Refusing: target path {resolved} is not inside the dedicated {LOCAL_TEST_DIR} directory."
        )
    if resolved in FORBIDDEN_ABSOLUTE_PATHS:
        raise LocalTestDatabaseSafetyError(f"Refusing: target path {resolved} is a real tracked repository database.")


def _engine(path: Path, *, enforce_foreign_keys: bool = True):
    LOCAL_TEST_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})

    if enforce_foreign_keys:
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def _has_marker(engine) -> bool:
    with engine.connect() as connection:
        exists = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
        ), {"name": MARKER_TABLE}).first()
        if not exists:
            return False
        row = connection.execute(text(f"SELECT marker FROM {MARKER_TABLE} LIMIT 1")).first()
        return bool(row) and row[0] == MARKER_VALUE


def _write_marker(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            f"CREATE TABLE IF NOT EXISTS {MARKER_TABLE} (marker TEXT NOT NULL, created_at TEXT NOT NULL)"
        ))
        connection.execute(text(f"DELETE FROM {MARKER_TABLE}"))
        connection.execute(text(
            f"INSERT INTO {MARKER_TABLE} (marker, created_at) VALUES (:marker, datetime('now'))"
        ), {"marker": MARKER_VALUE})


def cmd_create(path: Path) -> None:
    _assert_safe_target(path)
    engine = _engine(path)
    Base.metadata.create_all(engine)
    _write_marker(engine)
    print(f"Created local test schema at {path.resolve()}")


def cmd_seed(path: Path) -> None:
    _assert_safe_target(path)
    engine = _engine(path)
    if not _has_marker(engine):
        raise LocalTestDatabaseSafetyError(
            "Refusing: target database has no local-test sentinel marker. Run 'create' first."
        )
    from talent_local_test_data import build_dataset
    session = sessionmaker(bind=engine)()
    try:
        summary = build_dataset(session)
    finally:
        session.close()
    print("Seeded local test dataset:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


def cmd_status(path: Path) -> None:
    _assert_safe_target(path)
    resolved = path.resolve()
    if not resolved.exists():
        print(f"No local test database at {resolved}. Run 'create' then 'seed'.")
        return
    engine = _engine(path)
    marker_ok = _has_marker(engine)
    print(f"Local test database: {resolved}")
    print(f"Sentinel marker present: {marker_ok}")
    if marker_ok:
        with engine.connect() as connection:
            for table in ("school_groups", "students", "talent_programs", "talent_assessment_cycles",
                           "talent_student_assessments", "talent_review_candidates",
                           "talent_official_identifications"):
                try:
                    count = connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                except Exception:
                    count = "n/a (table not created yet)"
                print(f"  {table}: {count}")


def cmd_reset(path: Path, *, confirmed: bool) -> None:
    if not confirmed:
        raise LocalTestDatabaseSafetyError("Refusing: reset requires --confirm.")
    _assert_safe_target(path)
    engine = _engine(path)
    if path.resolve().exists() and not _has_marker(engine):
        raise LocalTestDatabaseSafetyError(
            "Refusing: existing target database has no local-test sentinel marker. "
            "This tool will not drop tables in a database it did not create."
        )
    # Drop/recreate with foreign_keys enforcement off on this dedicated connection
    # only: cross-table FK cycles (mirroring the same cycles the app's own SaaS
    # metadata has) otherwise make DROP TABLE order unresolvable under SQLite.
    drop_engine = _engine(path, enforce_foreign_keys=False)
    Base.metadata.drop_all(drop_engine)
    Base.metadata.create_all(drop_engine)
    _write_marker(drop_engine)
    print(f"Reset local test database at {path.resolve()}")


def cmd_reseed(path: Path, *, confirmed: bool) -> None:
    cmd_reset(path, confirmed=confirmed)
    cmd_seed(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("create", "seed", "status", "reset", "reseed"))
    parser.add_argument("--confirm", action="store_true", help="Required for reset/reseed.")
    args = parser.parse_args()
    path = resolve_target_path()
    try:
        if args.command == "create":
            cmd_create(path)
        elif args.command == "seed":
            cmd_seed(path)
        elif args.command == "status":
            cmd_status(path)
        elif args.command == "reset":
            cmd_reset(path, confirmed=args.confirm)
        elif args.command == "reseed":
            cmd_reseed(path, confirmed=args.confirm)
    except LocalTestDatabaseSafetyError as exc:
        print(f"SAFETY REFUSAL: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
