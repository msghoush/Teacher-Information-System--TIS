import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models  # noqa: F401 - register operational metadata
import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas.workspace_classification_admin_service import collect_workspace_diagnostics


def main() -> int:
    db = SessionLocal()
    try:
        report = collect_workspace_diagnostics(db)
        print(json.dumps({"mode": "read_only", "workspace_count": len(report), "workspaces": report}, indent=2))
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
