"""READ-ONLY audit of suspected duplicate Talent Programs and Talent configuration grants.

Final-closure Part B (central configuration authority). Programs, Frameworks,
Rubrics, Evaluation Plans and Periods are SchoolGroup-level shared configuration
owned once by the organization. Before that authority was enforced, a
Branch-scoped Administrator could author organization-wide configuration, so an
organization may hold several near-identical Programs (for example one per Branch).
This script LISTS suspected duplicates and their references so the owner can decide;
it never merges, deletes, renames or otherwise modifies anything.

Guarantees
* Only SELECT statements are issued. The connection is placed in a read-only
  transaction first (PostgreSQL ``SET TRANSACTION READ ONLY``; SQLite
  ``PRAGMA query_only=ON``) and is always rolled back, never committed.
* Output is a JSON document of aggregate counts, numeric ids, Program/Branch names
  and short structural hashes only. No Student, User, credential, secret or
  environment data is read or printed (user counts are aggregates, never ids).
* Exit codes: 0 = no suspected duplicate cluster and no non-Administrator
  configuration grant found; 2 = findings to review; 1 = the audit could not run.

Usage (owner, against the deployed database, from a shell that already has the
production ``DATABASE_URL`` exported)::

    python scripts/audit_talent_program_duplicates_readonly.py
    python scripts/audit_talent_program_duplicates_readonly.py --database-url <url>

This script must not be imported by runtime application code.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Permission keys whose holders can change shared Talent configuration.
CONFIG_MUTATION_KEYS = (
    "talent_programs.manage", "talent_programs.govern", "talent_programs.delete",
    "talent_programs.delete_competency", "talent_programs.delete_rubric_level",
    "talent_evaluation_plans.manage", "talent_evaluation_plans.govern",
    "talent_evaluation_plans.delete_period", "talent_evaluation_plans.manage_timeline",
    "talent_assessment_cycles.manage", "talent_assessment_cycles.govern",
)

# Tables that reference a Program and represent recorded history or operational evidence.
# Merging Programs would have to rewrite these rows (destructive for the audit trail).
HISTORY_TABLES = (
    ("assessments", "TalentStudentAssessment"),
    ("assessment_cycles", "TalentAssessmentCycle"),
    ("review_candidates", "TalentReviewCandidate"),
    ("official_identifications", "TalentOfficialIdentification"),
    ("educator_inputs", "TalentEducatorInput"),
)

_NON_WORD = re.compile(r"[^0-9a-z؀-ۿ]+")


def normalize_name(value: str) -> str:
    """Case, accent, hyphen, punctuation and whitespace insensitive comparison key."""
    text = unicodedata.normalize("NFKD", str(value or "")).lower()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(_NON_WORD.sub(" ", text).split())


def strip_branch_tokens(key: str, branch_keys: list[str]) -> str:
    """Remove any Branch name (prefix, suffix or parenthetical remnant) from a normalized key."""
    stripped = f" {key} "
    for branch_key in sorted({item for item in branch_keys if item}, key=len, reverse=True):
        stripped = stripped.replace(f" {branch_key} ", " ")
    return " ".join(stripped.split())


def _counts(session, model, group_column="program_id"):
    from sqlalchemy import func, inspect, select

    table = model.__table__
    if not inspect(session.connection()).has_table(table.name):
        return {}
    column = table.c[group_column]
    return {int(pid): int(count) for pid, count in session.execute(select(column, func.count()).group_by(column)).all()}


def _structure_signature(session, program_id, framework_id):
    """Short, program-independent hash of the newest framework structure (names, grades, levels)."""
    import models
    from sqlalchemy import select

    if framework_id is None:
        return None
    competencies = session.execute(
        select(models.FrameworkCompetency.grade_level, models.FrameworkCompetency.label)
        .where(models.FrameworkCompetency.framework_version_id == framework_id)
    ).all()
    levels = session.execute(
        select(models.TalentRubricLevel.code, models.TalentRubricLevel.display_order)
        .where(models.TalentRubricLevel.framework_version_id == framework_id)
    ).all()
    if not competencies and not levels:
        return None
    payload = json.dumps(
        {
            "competencies": sorted((str(g or ""), normalize_name(l)) for g, l in competencies),
            "levels": sorted((normalize_name(c), int(o)) for c, o in levels),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build_report(session) -> dict:
    """Pure read: builds the audit document from an already read-only session."""
    import models
    from sqlalchemy import inspect, select

    report = {
        "audit": "talent_program_duplicates_readonly",
        "read_only": True,
        "notes": [],
        "school_groups": [],
        "configuration_grants": {"role_grants": [], "user_override_allow_counts": []},
        "summary": {"programs": 0, "suspected_duplicate_clusters": 0, "non_administrator_configuration_grants": 0},
    }
    if not inspect(session.connection()).has_table(models.TalentProgram.__table__.name):
        report["notes"].append("section_unavailable:missing_table:talent_programs")
        return report

    framework_counts = _counts(session, models.TalentProgramFrameworkVersion)
    competency_counts = _counts(session, models.TalentCompetency)
    annual_counts = _counts(session, models.TalentProgramAcademicYearConfiguration)
    plan_counts = _counts(session, models.TalentAnnualEvaluationPlan)
    period_counts = _counts(session, models.TalentPlannedEvaluationPeriod)
    history_counts = {label: _counts(session, getattr(models, name)) for label, name in HISTORY_TABLES}

    programs = session.execute(
        select(models.TalentProgram.id, models.TalentProgram.school_group_id, models.TalentProgram.name, models.TalentProgram.status)
        .order_by(models.TalentProgram.school_group_id, models.TalentProgram.id)
    ).all()
    frameworks = session.execute(
        select(models.TalentProgramFrameworkVersion.program_id, models.TalentProgramFrameworkVersion.id,
               models.TalentProgramFrameworkVersion.status, models.TalentProgramFrameworkVersion.version_number)
        .order_by(models.TalentProgramFrameworkVersion.program_id, models.TalentProgramFrameworkVersion.version_number)
    ).all()
    frameworks_by_program = defaultdict(list)
    for program_id, framework_id, status, number in frameworks:
        frameworks_by_program[int(program_id)].append((int(framework_id), status, int(number)))
    years_by_program = defaultdict(set)
    for program_id, year_id in session.execute(
        select(models.TalentProgramAcademicYearConfiguration.program_id, models.TalentProgramAcademicYearConfiguration.academic_year_id)
    ).all():
        years_by_program[int(program_id)].add(int(year_id))

    branch_names = defaultdict(list)
    if inspect(session.connection()).has_table(models.Branch.__table__.name):
        for group_id, name in session.execute(select(models.Branch.school_group_id, models.Branch.name)).all():
            branch_names[int(group_id)].append(normalize_name(name))

    by_group = defaultdict(list)
    for program_id, group_id, name, status in programs:
        program_id, group_id = int(program_id), int(group_id)
        versions = frameworks_by_program.get(program_id, [])
        active = [item for item in versions if item[1] == "active"]
        newest = (active or versions or [None])[-1]
        history = {label: int(history_counts[label].get(program_id, 0)) for label, _ in HISTORY_TABLES}
        by_group[group_id].append({
            "program_id": program_id,
            "name": name,
            "status": status,
            "normalized_key": normalize_name(name),
            "branch_stripped_key": strip_branch_tokens(normalize_name(name), branch_names[group_id]),
            "framework_versions": int(framework_counts.get(program_id, 0)),
            "active_framework_versions": len(active),
            "competencies": int(competency_counts.get(program_id, 0)),
            "annual_configurations": int(annual_counts.get(program_id, 0)),
            "annual_configuration_academic_year_ids": sorted(years_by_program.get(program_id, ())),
            "evaluation_plans": int(plan_counts.get(program_id, 0)),
            "evaluation_periods": int(period_counts.get(program_id, 0)),
            "history_references": history,
            "history_reference_total": sum(history.values()),
            "structure_signature": _structure_signature(session, program_id, newest[0] if newest else None),
        })

    cluster_total = 0
    for group_id in sorted(by_group):
        rows = by_group[group_id]
        parent = {row["program_id"]: row["program_id"] for row in rows}

        def find(item):
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        reasons = defaultdict(set)
        buckets = defaultdict(list)
        for row in rows:
            buckets[("normalized_name", row["normalized_key"])].append(row["program_id"])
            if row["branch_stripped_key"]:
                buckets[("branch_name_variant", row["branch_stripped_key"])].append(row["program_id"])
            if row["structure_signature"]:
                buckets[("same_framework_structure", row["structure_signature"])].append(row["program_id"])
        for (reason, _key), members in buckets.items():
            if len(members) < 2:
                continue
            for other in members[1:]:
                parent[find(other)] = find(members[0])
            for member in members:
                reasons[member].add(reason)
        clusters = defaultdict(list)
        for row in rows:
            clusters[find(row["program_id"])].append(row)
        cluster_reports = []
        for members in clusters.values():
            if len(members) < 2:
                continue
            cluster_total += 1
            with_history = [row["program_id"] for row in members if row["history_reference_total"] > 0]
            overlapping_years = sorted({
                year for i, a in enumerate(members) for b in members[i + 1:]
                for year in set(a["annual_configuration_academic_year_ids"]) & set(b["annual_configuration_academic_year_ids"])
            })
            if len(with_history) >= 2 or overlapping_years:
                merge_risk = "destructive"
                merge_note = ("More than one member carries assessment/cycle/identification history or the same Academic Year "
                              "configuration; a merge would rewrite recorded history or collide. Do not merge automatically.")
            elif len(with_history) == 1:
                merge_risk = "requires_manual_review"
                merge_note = ("One member carries history; the others have none but still hold configuration that must be "
                              "reviewed before any retirement or consolidation.")
            else:
                merge_risk = "no_history_references"
                merge_note = "No member has recorded history; consolidation is still a manual owner decision."
            cluster_reports.append({
                "reasons": sorted({reason for row in members for reason in reasons[row["program_id"]]}),
                "program_ids": sorted(row["program_id"] for row in members),
                "members_with_history": sorted(with_history),
                "overlapping_academic_year_ids": overlapping_years,
                "merge_risk": merge_risk,
                "merge_note": merge_note,
            })
        report["school_groups"].append({
            "school_group_id": group_id,
            "program_count": len(rows),
            "programs": [
                {k: v for k, v in row.items() if k not in {"normalized_key", "branch_stripped_key"}}
                for row in rows
            ],
            "suspected_duplicate_clusters": sorted(cluster_reports, key=lambda item: item["program_ids"]),
        })
    report["summary"]["programs"] = len(programs)
    report["summary"]["suspected_duplicate_clusters"] = cluster_total

    # Stored grants of configuration authority to anything other than the Administrator default.
    grants = 0
    if inspect(session.connection()).has_table(models.RolePermission.__table__.name):
        rows = session.execute(
            select(models.RolePermission.school_group_id, models.RolePermission.role, models.RolePermission.permission_key)
            .where(models.RolePermission.is_allowed.is_(True))
            .where(models.RolePermission.permission_key.in_(CONFIG_MUTATION_KEYS))
            .where(models.RolePermission.role != "Administrator")
        ).all()
        aggregated = defaultdict(int)
        for group_id, role, key in rows:
            aggregated[(group_id, role, key)] += 1
        report["configuration_grants"]["role_grants"] = [
            {"school_group_id": g, "role": r, "permission_key": k, "stored_allow_rows": n}
            for (g, r, k), n in sorted(aggregated.items(), key=lambda item: (str(item[0][0]), item[0][1], item[0][2]))
        ]
        grants += len(aggregated)
    if inspect(session.connection()).has_table(models.UserPermissionOverride.__table__.name):
        rows = session.execute(
            select(models.UserPermissionOverride.school_group_id, models.UserPermissionOverride.permission_key)
            .where(models.UserPermissionOverride.is_allowed.is_(True))
            .where(models.UserPermissionOverride.permission_key.in_(CONFIG_MUTATION_KEYS))
        ).all()
        aggregated = defaultdict(int)
        for group_id, key in rows:
            aggregated[(group_id, key)] += 1
        report["configuration_grants"]["user_override_allow_counts"] = [
            {"school_group_id": g, "permission_key": k, "users_with_allow_override": n}
            for (g, k), n in sorted(aggregated.items(), key=lambda item: (str(item[0][0]), item[0][1]))
        ]
        grants += len(aggregated)
    report["configuration_grants"]["note"] = (
        "Stored allow rows for a non-Administrator role, and per-user Allow overrides (inert unless the role allows the key), "
        "are listed as counts only. Since Part B every configuration mutation additionally requires organization/global "
        "access scope; Branch-scoped holders are denied regardless."
    )
    report["summary"]["non_administrator_configuration_grants"] = grants
    return report


def open_read_only_session(database_url: str):
    """Return (session, connection) inside a read-only transaction. Caller must roll back and close."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    engine = create_engine(database_url)
    connection = engine.connect()
    dialect = connection.dialect.name
    if dialect == "postgresql":
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '60s'"))
    elif dialect == "sqlite":
        connection.execute(text("PRAGMA query_only=ON"))
    else:
        connection.close()
        raise RuntimeError(f"unsupported_database_dialect:{dialect}")
    return Session(bind=connection), connection


def perform_audit(database_url: str | None = None) -> tuple[dict, int]:
    url = (database_url or os.getenv("DATABASE_URL", "")).strip()
    if not url:
        return {"audit": "talent_program_duplicates_readonly", "read_only": True,
                "notes": ["audit_failed:DatabaseUrlMissing"]}, 1
    session = connection = None
    try:
        session, connection = open_read_only_session(url)
        report = build_report(session)
    except Exception as exc:  # never echo the URL or driver detail
        return {"audit": "talent_program_duplicates_readonly", "read_only": True,
                "notes": [f"audit_failed:{type(exc).__name__}"]}, 1
    finally:
        with contextlib.suppress(Exception):
            if session is not None:
                session.rollback()
                session.close()
        with contextlib.suppress(Exception):
            if connection is not None:
                connection.rollback()
                connection.close()
    findings = report["summary"]["suspected_duplicate_clusters"] or report["summary"]["non_administrator_configuration_grants"]
    return report, 2 if findings else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of suspected duplicate Talent Programs.")
    parser.add_argument("--database-url", default=None, help="Defaults to the DATABASE_URL environment variable.")
    args = parser.parse_args(argv)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        report, exit_code = perform_audit(args.database_url)
    sys.stdout.write(json.dumps(report, indent=2, default=str) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
