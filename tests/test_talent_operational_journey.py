"""Real HTTP acceptance contract for the Program-to-human-decision journey."""
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_current_user
from dependencies import get_db
from routers import (talent_programs, talent_evaluation_plans, talent_assessment_cycles,
                     talent_assessments, talent_review_candidates,
                     talent_official_identifications, talent_educator_inputs)
from student_academic_service import create_student, create_placement
from test_talent_student_assessment_competency_results import db, _user


def test_real_http_qualitative_program_to_review_and_separate_educator_input(db):
    _, session = db
    student = create_student(session, school_group_id=1, first_name="Test", last_name="Learner")
    create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    operator = _user("1000000099", branch=None, scope="ORGANIZATION")
    session.add(operator)
    session.commit()
    app = FastAPI()
    for module in (talent_programs, talent_evaluation_plans, talent_assessment_cycles,
                   talent_assessments, talent_review_candidates,
                   talent_official_identifications, talent_educator_inputs):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: operator
    with TestClient(app) as client:
        def call(method, path, data=None, status=200):
            response = client.request(method, "/api/talent/" + path, json=data)
            assert response.status_code == status, response.text
            return response.json()

        program = call("POST", "programs", {"name": "Performing Arts"}, 201)
        base = f"programs/{program['id']}"
        call("PATCH", base, {"description": "Expression and stage presence"})
        annual = call("PUT", base + "/academic-years/100", {"is_enabled": True, "eligible_grade_levels": ["1"]})
        framework = call("POST", base + "/frameworks", {"title": "Arts rubric"}, 201)
        fp = base + f"/frameworks/{framework['id']}"

        def configure(method, tail, data, status=200):
            current = call("GET", fp)
            return call(method, fp + tail, {"expected_revision": current["revision"], **data}, status)

        competency = call("POST", base + "/competencies", {"code": "EXPRESSION", "name": "Expression"}, 201)
        configure("POST", "/competencies", {"competency_id": competency["id"]}, 201)
        configure("PUT", "/rubric", {"name": "Qualitative achievement"})
        configure("POST", "/rubric/levels", {"code": "READY", "label": "Stage ready"}, 201)
        membership = call("GET", fp)["competencies"][0]
        level = call("GET", fp + "/configuration")["levels"][0]
        configure("PUT", "/rubric/descriptors", {"framework_competency_id": membership["id"], "rubric_level_id": level["id"], "descriptor": "Expresses the role consistently"})
        configure("PUT", "/review-candidate-policy", {"is_enabled": True, "match_mode": "all", "description": "Ready for review", "rules": [{"rule_type": "rubric_level_at_or_above", "framework_competency_id": membership["id"], "rubric_level_id": level["id"]}]})
        call("POST", base + "/lifecycle/active")
        current = call("GET", fp)
        configure("POST", "/activate", {"expected_fingerprint": current["semantic_fingerprint"]})
        plan = call("POST", "evaluation-plans", {"program_academic_year_configuration_id": annual["id"]}, 201)
        added = call("POST", f"evaluation-plans/{plan['id']}/periods", {"expected_plan_revision": plan["revision"], "label": "Autumn review", "is_required": True}, 201)
        plan = call("POST", f"evaluation-plans/{plan['id']}/activate", {"expected_plan_revision": added["plan_revision"]})
        cycle = call("POST", "assessment-cycles", {"program_id": program["id"], "academic_year_id": 100, "framework_version_id": framework["id"], "title": "Autumn assessment", "population_effective_at": "2026-10-01T00:00:00Z"}, 201)
        linked = call("POST", f"assessment-cycles/{cycle['id']}/link-period", {"planned_period_id": added["period"]["id"], "expected_plan_revision": plan["revision"], "expected_cycle_revision": cycle["revision"]})
        call("POST", f"assessment-cycles/{cycle['id']}/open", {"expected_revision": linked["cycle_revision"]})
        member = call("GET", f"assessment-cycles/{cycle['id']}/population")["members"][0]
        assert member["student_name"] == "Test Learner"
        assessment = call("POST", "assessments", {"cycle_id": cycle["id"], "cycle_population_member_id": member["id"]}, 201)
        assert assessment["context"]["grade_level"] == "1"
        path = f"assessments/{assessment['id']}"
        result_path = path + f"/competency-results/{membership['id']}"
        saved = call("PUT", result_path, {"rubric_level_id": level["id"], "expected_revision": assessment["revision"], "evidence": "Consistent expression"})
        call("PUT", result_path, {"rubric_level_id": level["id"], "expected_revision": assessment["revision"], "evidence": "Stale overwrite"}, 409)
        assert call("GET", path + "/competency-results")[0]["evidence"] == "Consistent expression"
        completed = call("POST", path + "/complete", {"expected_revision": saved["assessment"]["revision"]})
        assert completed["kpi_result"] is None
        candidate = call("POST", "review-candidates/evaluate", {"assessment_id": assessment["id"]}, 201)["candidate"]
        assert call("GET", "official-identifications") == []
        decision_data = {"review_candidate_id": candidate["id"], "decision": "identified", "rationale": "Human review complete"}
        call("POST", "official-identifications", decision_data, 409)
        call("POST", f"review-candidates/{candidate['id']}/review")
        assert call("GET", "official-identifications") == []
        call("POST", "official-identifications", decision_data, 201)
        call("POST", "official-identifications", decision_data, 409)
        binding = {"student_id": student.id, "program_id": program["id"], "academic_year_id": 100, "cycle_id": cycle["id"], "cycle_population_member_id": member["id"], "assessment_id": assessment["id"], "observed_at": "2026-10-01T12:00:00Z", "category": "observation", "content": "Separate educator observation"}
        educator = call("POST", "educator-inputs", binding, 201)
        call("POST", f"educator-inputs/{educator['id']}/amend", {**binding, "content": "Amended observation"}, 201)
        assert len(call("GET", f"educator-inputs/{educator['id']}/history")) == 2
        assert call("GET", path)["revision"] == completed["revision"]
        assert call("GET", path + "/competency-results")[0]["evidence"] == "Consistent expression"
