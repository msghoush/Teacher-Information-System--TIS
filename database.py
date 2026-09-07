import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

# Fall back to the local SQLite database when DATABASE_URL is not configured.
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_URL = f"sqlite:///{(BASE_DIR / 'tis.db').as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

# Create engine
engine = create_engine(DATABASE_URL, **engine_kwargs)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ---------------------------------------------------------------------------
# M10 Organization Analytics: dedicated REPEATABLE READ session boundary.
#
# See `docs/adr/0029-m10-organization-analytics-repeatable-read-boundary.md`
# (ADR 0029, governed after B11-D's proven READ COMMITTED same-request
# mixed-snapshot evidence). This binds a SEPARATE sessionmaker to a
# `engine.execution_options(...)` proxy so the isolation level is applied
# only to sessions created through `M10OrganizationAnalyticsSessionLocal` -
# it shares the same underlying connection pool as `engine` but does not
# alter `engine`'s own default isolation level, so `SessionLocal`/`get_db`
# and every other route/module are completely unaffected.
#
# `REPEATABLE READ` is a PostgreSQL-specific isolation level string; the
# SQLAlchemy SQLite dialect used by the local `tis.db` fallback and by the
# in-memory fixtures in `tests/` does not accept it. This is therefore
# strictly backend-conditional: on a non-PostgreSQL `DATABASE_URL`, the M10
# sessionmaker binds to the plain `engine` (unchanged default isolation)
# instead of raising or silently changing SQLite behavior.
if DATABASE_URL.startswith("postgresql"):
    _m10_organization_analytics_bind = engine.execution_options(isolation_level="REPEATABLE READ")
else:
    _m10_organization_analytics_bind = engine

M10OrganizationAnalyticsSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=_m10_organization_analytics_bind,
)

# Base
Base = declarative_base()
