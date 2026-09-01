from __future__ import annotations

from threading import Event
from typing import Protocol


class TimetableSolver(Protocol):
    """Solver-neutral boundary consumed by the timetable Workflow worker."""

    name: str

    def solve(
        self,
        problem: dict,
        *,
        timeout_seconds: float,
        seed: int,
        search_workers: int,
        cancel_event: Event | None = None,
        optimize_soft_constraints: bool = True,
        solution_hint: list[dict] | None = None,
    ) -> dict: ...

    def diagnose_infeasible(
        self,
        problem: dict,
        *,
        timeout_seconds: float,
        seed: int,
        search_workers: int,
    ) -> dict: ...


class CpSatTimetableSolver:
    """Release 1 production adapter for the existing OR-Tools CP-SAT engine."""

    name = "OR-Tools CP-SAT"

    @staticmethod
    def solve(
        problem: dict,
        *,
        timeout_seconds: float,
        seed: int,
        search_workers: int,
        cancel_event: Event | None = None,
        optimize_soft_constraints: bool = True,
        solution_hint: list[dict] | None = None,
    ) -> dict:
        from timetable_cp_sat_solver import solve_timetable

        return solve_timetable(
            problem,
            timeout_seconds=timeout_seconds,
            seed=seed,
            search_workers=search_workers,
            cancel_event=cancel_event,
            optimize_soft_constraints=optimize_soft_constraints,
            solution_hint=solution_hint,
        )

    @staticmethod
    def diagnose_infeasible(
        problem: dict,
        *,
        timeout_seconds: float,
        seed: int,
        search_workers: int,
    ) -> dict:
        from timetable_cp_sat_solver import diagnose_infeasible_problem

        return diagnose_infeasible_problem(
            problem,
            timeout_seconds=timeout_seconds,
            seed=seed,
            search_workers=search_workers,
        )


DEFAULT_TIMETABLE_SOLVER: TimetableSolver = CpSatTimetableSolver()
