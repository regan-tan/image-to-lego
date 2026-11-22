import pytest
from ortools.sat.python import cp_model

from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.m13f_connectivity_optimization import (
    add_exact_mask_constraints,
    add_selectable_root_variables,
    add_separator_cut,
    add_single_component_constraint,
    audit_contact_graph_subset,
    mechanical_connectivity_graph,
    selected_graph_component_count,
    selected_graph_components,
    separator_cut,
    separator_cuts,
)
from app.conversion.part_catalogue import PART_BY_ID


def _plate(x: int, y: int, z: int) -> BrickPlacement:
    return BrickPlacement(PART_BY_ID["3024"], GridPosition(x, y, z), 0)


def _solve(model: cp_model.CpModel) -> tuple[str, cp_model.CpSolver]:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    return solver.status_name(solver.solve(model)), solver


def test_flow_rejects_disconnected_selected_candidates() -> None:
    candidates = (_plate(0, 0, 1), _plate(4, 0, 0))
    graph = mechanical_connectivity_graph(candidates, (_plate(0, 0, 0),))
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(2))
    model.add(selected[0] == 1)
    model.add(selected[1] == 1)
    add_single_component_constraint(model, selected, graph)

    status, _solver = _solve(model)

    assert status == "INFEASIBLE"


def test_flow_accepts_optional_connector_and_independent_graph_check() -> None:
    candidates = (_plate(0, 0, 1), _plate(0, 0, 2))
    graph = mechanical_connectivity_graph(candidates, (_plate(0, 0, 0),))
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(2))
    model.add(selected[0] == 1)
    model.add(selected[1] == 1)
    encoding = add_single_component_constraint(model, selected, graph)

    status, _solver = _solve(model)

    assert status in {"OPTIMAL", "FEASIBLE"}
    assert encoding.root_mode == "first-locked-placement"
    assert selected_graph_component_count(graph, (0, 1)) == 1


def test_unlocked_graph_selects_a_valid_root() -> None:
    graph = mechanical_connectivity_graph((_plate(0, 0, 0), _plate(0, 0, 1)), ())
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(2))
    model.add(sum(selected) == 2)
    encoding = add_single_component_constraint(model, selected, graph)

    status, _solver = _solve(model)

    assert status in {"OPTIMAL", "FEASIBLE"}
    assert encoding.root_mode == "selected-candidate"
    assert encoding.root_selection_variable_count == 2


def test_exact_mask_constraints_pin_and_detect_inseparable_masks() -> None:
    model = cp_model.CpModel()
    selected = (model.new_bool_var("x_0"),)
    add_exact_mask_constraints(
        model,
        selected,
        ((("front", 0, 0),),),
        (),
        {("front", 0, 0)},
    )
    status, solver = _solve(model)
    assert status in {"OPTIMAL", "FEASIBLE"}
    assert solver.boolean_value(selected[0])

    invalid = cp_model.CpModel()
    with pytest.raises(ValueError, match="inseparable"):
        add_exact_mask_constraints(
            invalid,
            (invalid.new_bool_var("x_0"),),
            ((("front", 0, 0), ("front", 1, 0)),),
            (),
            {("front", 0, 0)},
        )


def test_fixed_root_separator_cut_requires_the_missing_connector() -> None:
    root = _plate(0, 0, 0)
    connector = _plate(0, 0, 1)
    remote = _plate(0, 0, 2)
    graph = mechanical_connectivity_graph((connector, remote), (root,))
    assert selected_graph_components(graph, (1,)) == ((1,), (2,))
    cut = separator_cut(graph, (1,))
    assert cut.boundary_candidate_indices == (0,)

    disconnected = cp_model.CpModel()
    selected = tuple(disconnected.new_bool_var(f"x_{index}") for index in range(2))
    disconnected.add(selected[1] == 1)
    disconnected.add(selected[0] == 0)
    add_separator_cut(
        disconnected,
        selected,
        cut,
        fixed_root_node=2,
    )
    status, _solver = _solve(disconnected)
    assert status == "INFEASIBLE"

    connected = cp_model.CpModel()
    selected = tuple(connected.new_bool_var(f"x_{index}") for index in range(2))
    connected.add(selected[0] == 1)
    connected.add(selected[1] == 1)
    add_separator_cut(connected, selected, cut, fixed_root_node=2)
    status, _solver = _solve(connected)
    assert status in {"OPTIMAL", "FEASIBLE"}


def test_multiple_separator_cuts_cover_every_selected_component_vertex() -> None:
    root = _plate(0, 0, 0)
    connector = _plate(0, 0, 1)
    first_remote = _plate(0, 0, 2)
    second_remote = _plate(1, 0, 2)
    graph = mechanical_connectivity_graph((connector, first_remote, second_remote), (root,))

    cuts = separator_cuts(graph, (1, 2))

    assert [cut.representative_candidate_index for cut in cuts] == [1, 2]
    assert all(cut.boundary_candidate_indices == (0,) for cut in cuts)
    assert len({cut.canonical_identifier for cut in cuts}) == 2


def test_contact_audit_requires_real_positive_negative_and_overlap_controls() -> None:
    root = _plate(0, 0, 0)
    connector = _plate(0, 0, 1)
    remote = _plate(0, 0, 3)

    audit = audit_contact_graph_subset(
        (root, connector, remote, root),
        required_positive_pairs=((0, 1),),
        required_negative_pairs=((0, 2),),
        required_overlapping_pairs=((0, 3),),
    )

    assert audit.matches
    assert audit.required_positive_pairs_found == 1
    assert audit.required_negative_pairs_absent == 1
    assert audit.required_overlapping_pair_count == 1


def test_selectable_root_cut_does_not_exclude_a_connected_assembly() -> None:
    graph = mechanical_connectivity_graph((_plate(0, 0, 0), _plate(0, 0, 1)), ())
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(2))
    model.add(sum(selected) == 2)
    roots = add_selectable_root_variables(model, selected, graph)
    add_separator_cut(
        model,
        selected,
        separator_cut(graph, (0,)),
        fixed_root_node=None,
        selectable_roots=roots,
    )

    status, _solver = _solve(model)

    assert status in {"OPTIMAL", "FEASIBLE"}


def test_flow_and_separator_cuts_have_matching_minimum_on_a_chain() -> None:
    root = _plate(0, 0, 0)
    connector = _plate(0, 0, 1)
    remote = _plate(0, 0, 2)
    graph = mechanical_connectivity_graph((connector, remote), (root,))

    flow_model = cp_model.CpModel()
    flow_selected = tuple(flow_model.new_bool_var(f"x_{index}") for index in range(2))
    flow_model.add(flow_selected[1] == 1)
    add_single_component_constraint(flow_model, flow_selected, graph)
    flow_model.minimize(sum(flow_selected))
    status, flow_solver = _solve(flow_model)
    assert status == "OPTIMAL"

    cut_model = cp_model.CpModel()
    cut_selected = tuple(cut_model.new_bool_var(f"x_{index}") for index in range(2))
    cut_model.add(cut_selected[1] == 1)
    cut_model.minimize(sum(cut_selected))
    status, cut_solver = _solve(cut_model)
    assert status == "OPTIMAL"
    disconnected_component = next(
        component for component in selected_graph_components(graph, (1,)) if 2 not in component
    )
    add_separator_cut(
        cut_model,
        cut_selected,
        separator_cut(graph, disconnected_component),
        fixed_root_node=2,
    )
    status, cut_solver = _solve(cut_model)
    assert status == "OPTIMAL"
    assert flow_solver.objective_value == cut_solver.objective_value == 2
