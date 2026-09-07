from database import M10OrganizationAnalyticsSessionLocal, SessionLocal

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_m10_organization_analytics_db():
    """Session boundary for the seven M10 Organization Intelligence routes only.

    See ADR 0029. On PostgreSQL this session runs at `REPEATABLE READ`
    (`database.M10OrganizationAnalyticsSessionLocal`), fixing one snapshot for
    the whole request before its first statement (context/access resolution)
    executes, so every later statement in the same request - aggregate reads,
    Candidate/Identification reads, privacy-closure inputs - observes that
    same snapshot. It is never used by any other route, and it does not
    change `get_db`'s/`SessionLocal`'s default isolation for the rest of the
    application. On non-PostgreSQL backends it behaves exactly like `get_db`.
    """
    db = M10OrganizationAnalyticsSessionLocal()
    try:
        yield db
    finally:
        db.close()
