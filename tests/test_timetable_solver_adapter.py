from __future__ import annotations

import timetable_cp_sat_solver
from timetable_solver import CpSatTimetableSolver


def test_cp_sat_adapter_forwards_solve_contract(monkeypatch):
    captured = {}

    def fake_solve(problem, **kwargs):
        captured.update(problem=problem, **kwargs)
        return {"outcome": "feasible", "placements": []}

    monkeypatch.setattr(timetable_cp_sat_solver, "solve_timetable", fake_solve)
    hint = [{"section_id": 1}]
    result = CpSatTimetableSolver().solve(
        {"scope": {"branch_id": 10}},
        timeout_seconds=12,
        seed=7,
        search_workers=2,
        optimize_soft_constraints=False,
        solution_hint=hint,
    )

    assert result["outcome"] == "feasible"
    assert captured["timeout_seconds"] == 12
    assert captured["seed"] == 7
    assert captured["search_workers"] == 2
    assert captured["optimize_soft_constraints"] is False
    assert captured["solution_hint"] is hint


def test_cp_sat_adapter_forwards_diagnostic_contract(monkeypatch):
    captured = {}

    def fake_diagnose(problem, **kwargs):
        captured.update(problem=problem, **kwargs)
        return {"category": "base_model"}

    monkeypatch.setattr(
        timetable_cp_sat_solver, "diagnose_infeasible_problem", fake_diagnose
    )
    result = CpSatTimetableSolver().diagnose_infeasible(
        {"demands": []}, timeout_seconds=9, seed=13, search_workers=1
    )

    assert result == {"category": "base_model"}
    assert captured["timeout_seconds"] == 9
    assert captured["seed"] == 13
    assert captured["search_workers"] == 1
