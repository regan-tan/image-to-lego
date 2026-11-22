from ortools.sat.python import cp_model

from app.conversion.m13e_duck_iou_dominance import IoUDominanceModel
from app.conversion.m13e_duck_mean_iou_guided import linearized_mean_iou_objective
from app.conversion.m13f_duck_coarse_budget_frontier import CoarseRequirement
from app.conversion.m13f_minimum_violation_audit import (
    add_exact_surrogate_target,
    add_minimum_violation_objective,
    exact_surrogate_matches,
    independently_count_violations,
    minimum_violation_conclusion,
)


def _model() -> tuple[IoUDominanceModel, cp_model.IntVar]:
    model = cp_model.CpModel()
    selected = model.new_bool_var("selected")
    return (
        IoUDominanceModel(
            model,
            (selected,),
            {view: selected for view in ("front", "side", "top")},
            {view: 0 for view in ("front", "side", "top")},
            {},
            {view: 1 for view in ("front", "side", "top")},
            {},
        ),
        selected,
    )


def test_exact_target_and_minimum_violation_encoding() -> None:
    built, selected = _model()
    objective = linearized_mean_iou_objective(
        {view: 1 for view in ("front", "side", "top")},
        {view: {"truePositives": 1, "falsePositives": 0} for view in ("front", "side", "top")},
    )
    target = sum(objective.true_positive_coefficients.values())
    add_exact_surrogate_target(built, objective, target)
    violation = built.model.new_bool_var("violation")
    built.model.add(selected + violation == 1)
    add_minimum_violation_objective(built.model, (violation,))
    solver = cp_model.CpSolver()
    assert solver.status_name(solver.solve(built.model)) == "OPTIMAL"
    assert solver.value(selected) == 1
    assert solver.value(violation) == 0


def test_impossible_target_is_infeasible() -> None:
    built, _ = _model()
    objective = linearized_mean_iou_objective(
        {view: 1 for view in ("front", "side", "top")},
        {view: {"truePositives": 1, "falsePositives": 0} for view in ("front", "side", "top")},
    )
    add_exact_surrogate_target(built, objective, 1)
    assert cp_model.CpSolver().status_name(cp_model.CpSolver().solve(built.model)) == "INFEASIBLE"


def test_independent_count_and_objective_evaluation_are_not_solver_values() -> None:
    requirements = (
        CoarseRequirement(("front", 0, 0), (0,), False),
        CoarseRequirement(("front", 1, 0), (1,), False),
        CoarseRequirement(("front", 2, 0), (), True),
    )
    assert independently_count_violations(requirements, (0,)) == 1
    objective = linearized_mean_iou_objective(
        {view: 1 for view in ("front", "side", "top")},
        {view: {"truePositives": 1, "falsePositives": 0} for view in ("front", "side", "top")},
    )
    views = {view: {"truePositives": 1, "falsePositives": 0} for view in ("front", "side", "top")}
    assert exact_surrogate_matches(
        views, objective, sum(objective.true_positive_coefficients.values())
    )


def test_status_handling_does_not_claim_minimality_from_an_incumbent() -> None:
    assert minimum_violation_conclusion("OPTIMAL") == "PROVEN_MINIMUM"
    assert minimum_violation_conclusion("FEASIBLE") == "UPPER_AND_LOWER_BOUNDS_ONLY"
    assert minimum_violation_conclusion("UNKNOWN") == "INCONCLUSIVE"
