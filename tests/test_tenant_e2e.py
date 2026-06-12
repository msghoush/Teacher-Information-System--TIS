import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TenantEndToEndIsolationTests(unittest.TestCase):
    def test_two_school_http_isolation_runner(self):
        repo_root = Path(__file__).resolve().parents[1]
        runner = repo_root / "tests" / "tenant_e2e_runner.py"

        with tempfile.TemporaryDirectory(prefix="tis_tenant_e2e_") as temp_dir:
            db_path = Path(temp_dir) / "tenant_e2e.db"
            env = os.environ.copy()
            env.update(
                {
                    "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
                    "TIS_SESSION_SECRET": "tenant-e2e-session-secret-that-is-long-enough",
                    "TIS_ENV": "testing",
                    "TIS_COOKIE_SECURE": "0",
                    "TIS_NOTIFICATION_DIAGNOSTIC": "0",
                }
            )
            result = subprocess.run(
                [sys.executable, str(runner)],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )

        if result.returncode != 0:
            self.fail(
                "tenant E2E runner failed\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        output_lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(output_lines, "tenant E2E runner produced no output")
        payload = json.loads(output_lines[-1])
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(
            {
                "list",
                "detail",
                "create",
                "edit",
                "delete",
                "export",
                "import",
                "reports",
                "notifications",
                "foreign_keys",
            },
            set(payload["checks"]),
        )


if __name__ == "__main__":
    unittest.main()
