"""Why an aggregate Classification reads "Unavailable" (production follow-up, Part 1 C).

Diagnosis, pinned as behavior. A small Branch/Program with a handful of completed,
individually classified Students is NOT publishable as an aggregate under the approved
Release 1 privacy provider (``ConfiguredRelease1PrivacyPolicy``: a governed minimum
cohort of 5 applied to EVERY Classification band cell, class P4, followed by
complementary suppression; ADR 0028 / B11-E F1, ADR 0044 Agent 3 amendment). Each band
below the floor (including a band with zero Students) is suppressed at the primary stage;
the backend serialises those cells with ``count``/``percentage`` = ``None`` and the UI
renders them as "Unavailable". This is the intended protection, not a defect:

* the pipeline stage that hides the values is ``apply_primary_privacy`` (per-band cell),
  never the classification service (each Student IS classified) and never the
  aggregation grain (pooling across Programs would only add cohort size);
* broader selections publish exactly the bands that clear the floor;
* an absent privacy configuration fails closed for the whole family;
* nothing hidden ever reaches the payload (no count, percentage, or raw value).
"""

from __future__ import annotations

import json
from datetime import datetime

import models
from student_academic_service import create_placement, create_student
from talent_analytics_privacy import AllowAllTestPolicy
from talent_classification_service import CLASSIFICATION_LABELS, assessment_classification
from talent_dashboard_service import build_dashboard
from talent_organization_analytics_providers import ConfiguredRelease1PrivacyPolicy
from talent_student_assessment_service import complete_assessment, set_competency_result, start_assessment
from test_talent_classification import build_program, complete_with_level, db  # noqa: F401 (fixture)

# level index -> band on the five level rubric: 0 NI, 1 Developing, 2 Meets, 3 Advanced, 4 Exceptional
BAND_OF = dict(zip(range(5), CLASSIFICATION_LABELS))


def add_completed(session, cycle, competency, level, name):
    student = create_student(session, school_group_id=1, first_name=name, last_name="Learner")
    create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100, branch_id=10,
                     planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    session.commit()
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, student_id=student.id)
    _, assessment = set_competency_result(
        session, school_group_id=1, assessment_id=assessment.id, framework_competency_id=competency.id,
        rubric_level_id=level.id, expected_revision=assessment.revision, evidence="evidence")
    complete_assessment(session, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)
    session.commit()


def populate(session, counts):
    """One Program, one Branch, one year: ``counts[i]`` completed Students in band ``i``."""
    program, framework, cycle, member, competency, levels, first = build_program(session, level_count=5)
    plan = [level for level, count in enumerate(counts) for _ in range(count)]
    complete_with_level(session, member, competency, levels[plan[0]])
    for index, level in enumerate(plan[1:]):
        add_completed(session, cycle, competency, levels[level], f"S{index}")
    return program


def aggregate(session, policy, **filters):
    return build_dashboard(session, group_id=1, year_id=100, visible_branches=None, filters=filters,
                           policy=policy, learning_style_allowed=True)


def release_policy():
    return ConfiguredRelease1PrivacyPolicy(minimum_cohort=5)


def states(payload):
    return {bucket["label"]: (bucket["state"], bucket["count"]) for bucket in payload["classification"]["buckets"]}


def test_small_branch_every_band_below_floor_is_protected_while_students_are_all_classified(db):
    """Realistic small Branch: 6 completed Students spread over three bands."""
    populate(db, [0, 1, 2, 3, 0])  # Developing 1, Meets 2, Advanced 3
    payload = aggregate(db, release_policy())
    classification = payload["classification"]
    # The population and every Student's own classification are fine ...
    assert payload["distinct_students"] == {"state": "visible", "value": 6}
    assert classification["total"] == {"state": "visible", "value": 6}
    # ... but each band is below the governed floor, so the PRIMARY stage hides all of them.
    assert {state for state, _ in states(payload).values()} == {"suppressed"}
    assert all(count is None for _, count in states(payload).values())
    assert all(bucket["percentage"] is None for bucket in classification["buckets"])
    # Nothing hidden is present anywhere in the serialised classification payload.
    body = json.dumps(classification)
    for token in ('"count": 1', '"count": 2', '"count": 3', '"percentage": 16', '"percentage": 33', '"percentage": 50'):
        assert token not in body, token


def test_the_classification_service_itself_classifies_every_completed_student(db):
    """The Unavailable state is produced by privacy, not by classification failing."""
    populate(db, [0, 1, 2, 3, 0])
    rows = db.query(models.TalentStudentAssessment).filter_by(status="completed", is_current=True).all()
    assert len(rows) == 6
    bands = sorted(assessment_classification(db, row)["classification"] for row in rows)
    assert bands == sorted(["Developing", "Meets Expectations", "Meets Expectations", "Advanced", "Advanced", "Advanced"])


def test_without_a_privacy_policy_the_same_cohort_is_fully_visible(db):
    """Proves the diagnosis: only the privacy stage differs between visible and Unavailable."""
    populate(db, [0, 1, 2, 3, 0])
    payload = aggregate(db, AllowAllTestPolicy())
    assert states(payload) == {"Needs Improvement": ("visible", 0), "Developing": ("visible", 1),
                               "Meets Expectations": ("visible", 2), "Advanced": ("visible", 3), "Exceptional": ("visible", 0)}


def test_bands_that_clear_the_floor_publish_and_smaller_bands_stay_protected(db):
    populate(db, [7, 4, 0, 5, 6])  # NI 7, Developing 4, Meets 0, Advanced 5, Exceptional 6 -> 22
    payload = aggregate(db, release_policy())
    result = states(payload)
    assert result["Needs Improvement"] == ("visible", 7)
    assert result["Advanced"] == ("visible", 5)
    assert result["Exceptional"] == ("visible", 6)
    assert result["Developing"] == ("suppressed", None)
    assert result["Meets Expectations"] == ("suppressed", None)  # a zero band is also below the floor
    assert payload["classification"]["total"] == {"state": "visible", "value": 22}


def test_total_below_the_floor_protects_the_whole_distribution(db):
    populate(db, [0, 2, 1, 1, 0])  # 4 Students
    payload = aggregate(db, release_policy())
    assert payload["classification"]["total"]["state"] == "suppressed"
    assert payload["classification"]["total"]["value"] is None
    assert all(count is None for _, count in states(payload).values())


def test_absent_privacy_configuration_fails_closed_for_the_family(db):
    populate(db, [7, 4, 0, 5, 6])
    payload = aggregate(db, None)
    assert payload["classification"] == {"state": "restricted", "total": {"state": "restricted", "value": None}, "buckets": []}


def test_selecting_the_only_program_cannot_help_because_the_cohort_itself_is_below_the_floor(db):
    program = populate(db, [0, 1, 2, 3, 0])
    scoped = aggregate(db, release_policy(), program_id=str(program.id))
    unscoped = aggregate(db, release_policy())
    assert states(scoped) == states(unscoped)
