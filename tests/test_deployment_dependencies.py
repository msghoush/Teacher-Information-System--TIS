"""Deployment dependency guard: every SQLAlchemy PostgreSQL driver family a
DATABASE_URL may select must have its DBAPI declared in requirements.txt.

Dependency-free: parses requirements.txt only and never connects to a database.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]

# URL -> (SQLAlchemy dialect module, DBAPI distribution names that satisfy it)
DRIVER_FAMILIES = {
    "postgresql://u:p@h/db": ("sqlalchemy.dialects.postgresql.psycopg2", {"psycopg2-binary", "psycopg2"}),
    "postgresql+psycopg2://u:p@h/db": ("sqlalchemy.dialects.postgresql.psycopg2", {"psycopg2-binary", "psycopg2"}),
    "postgresql+psycopg://u:p@h/db": ("sqlalchemy.dialects.postgresql.psycopg", {"psycopg"}),
}


def _declared_requirements(filename="requirements.txt"):
    names = set()
    for raw in (ROOT / filename).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if match:
            names.add(re.sub(r"[-_.]+", "-", match.group(0)).lower())
    return names


@pytest.mark.parametrize("url", sorted(DRIVER_FAMILIES))
def test_each_postgresql_driver_family_has_a_declared_requirement(url):
    module, distributions = DRIVER_FAMILIES[url]
    dialect_cls = make_url(url).get_dialect()
    assert dialect_cls.__module__ == module
    assert _declared_requirements() & distributions, (
        f"{url} resolves to {module} but requirements.txt declares none of {sorted(distributions)}"
    )


def test_psycopg_v3_requirement_uses_binary_extra():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^psycopg\[binary\]", text, re.MULTILINE)


def test_repository_hardcodes_no_driver_scheme_without_requirement():
    declared = _declared_requirements()
    scheme = re.compile(r"postgresql\+([a-z0-9_]+)://")
    required = {"psycopg2": {"psycopg2-binary", "psycopg2"}, "psycopg": {"psycopg"}}
    for path in list(ROOT.glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        for driver in scheme.findall(path.read_text(encoding="utf-8", errors="ignore")):
            assert driver in required, f"{path.name} hard-codes undeclared driver {driver}"
            assert declared & required[driver], f"{path.name} uses {driver} without a requirement"
