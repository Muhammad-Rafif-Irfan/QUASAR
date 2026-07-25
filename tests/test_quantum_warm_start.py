from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from app.services.quantum_hybrid.warm_start import (
    Bottleneck,
    DeliveryAssignment,
    EvaluatedSolution,
    MoveCandidate,
    RouteProblem,
    Solution,
    apply_move,
    detect_bottlenecks,
    evaluate_solution,
    extract_difficult_neighborhood,
    generate_candidate_moves,
    improvement_gate,
    run_quasar_qaoa_xy_hybrid,
    validate_solution,
)
from app.services.quantum_hybrid.hamiltonian import (
    CandidateHamiltonian,
    brute_force_exact_one,
    decode_one_hot_bitstring,
    evaluate_bitstring_energy,
)


def cvrp_problem() -> RouteProblem:
    return RouteProblem.from_data(
        [
            [0, 10, 1, 10],
            [10, 0, 1, 1],
            [1, 1, 0, 10],
            [10, 1, 10, 0],
        ],
        [0, 1, 1, 1],
        [3],
        [0],
        problem_type="cvrp",
    )


def sdvrp_problem() -> RouteProblem:
    return RouteProblem.from_data(
        [[0, 5, 1], [5, 0, 1], [1, 1, 0]],
        [0, 2, 1],
        [3, 2],
        [0, 0],
        problem_type="sdvrp",
    )


def sdvrp_seed() -> Solution:
    return Solution(
        routes={"0": [0, 1, 2, 0], "1": [0, 1, 0]},
        deliveries=(
            DeliveryAssignment(0, 1, 1, 1.0),
            DeliveryAssignment(0, 2, 2, 1.0),
            DeliveryAssignment(1, 1, 1, 1.0),
        ),
    )


def test_explicit_problem_type() -> None:
    assert cvrp_problem().problem_type == "cvrp"
    assert sdvrp_problem().problem_type == "sdvrp"
    with pytest.raises(ValueError):
        RouteProblem.from_data([[0, 1], [1, 0]], [0, 1], [1], [0], problem_type="vrp")


def test_multi_vehicle_cvrp_is_not_sdvrp() -> None:
    problem = RouteProblem.from_data(
        [[0, 1, 1], [1, 0, 1], [1, 1, 0]],
        [0, 1, 1],
        [1, 1],
        [0, 0],
        problem_type="cvrp",
    )
    assert problem.problem_type == "cvrp"
    assert not problem.split_delivery


def test_cvrp_exact_once_validation() -> None:
    problem = cvrp_problem()
    assert not validate_solution(problem, Solution({"0": [0, 1, 2, 3, 0]}))
    errors = validate_solution(problem, Solution({"0": [0, 1, 1, 3, 0]}))
    assert any("exactly once" in error for error in errors)


def test_sdvrp_position_aware_validation() -> None:
    problem = sdvrp_problem()
    seed = sdvrp_seed()
    assert not validate_solution(problem, seed)
    repeated = Solution(
        {"0": [0, 1, 1, 2, 0], "1": [0, 0]},
        (
            DeliveryAssignment(0, 1, 1, 0.5),
            DeliveryAssignment(0, 2, 1, 1.5),
            DeliveryAssignment(0, 3, 2, 1.0),
        ),
    )
    assert not validate_solution(problem, repeated)


def test_sdvrp_rejects_unmatched_delivery() -> None:
    problem = sdvrp_problem()
    invalid = Solution(
        {"0": [0, 1, 2, 0], "1": [0, 1, 0]},
        (
            DeliveryAssignment(0, 2, 1, 1.0),
            DeliveryAssignment(0, 2, 2, 1.0),
            DeliveryAssignment(1, 1, 1, 1.0),
        ),
    )
    assert any("matching route visit" in error for error in validate_solution(problem, invalid))


def test_bottleneck_severity_is_normalized_and_sdvrp_load_is_quantity_based() -> None:
    problem = sdvrp_problem()
    items = detect_bottlenecks(problem, sdvrp_seed(), capacity_pressure_threshold=0.0)
    assert items
    assert all(0.0 <= item.severity <= 1.0 for item in items)
    capacity = [item for item in items if item.bottleneck_id == "capacity_v0"][0]
    assert capacity.evidence["load"] == pytest.approx(2.0)


def test_targeted_neighborhood_is_compact() -> None:
    problem = cvrp_problem()
    seed = Solution({"0": [0, 1, 2, 3, 0]})
    bottleneck = Bottleneck(
        "edge",
        "high_cost_edge",
        1.0,
        (1, 2),
        (0,),
        ((0, 1, 2),),
        ((0, 1), (0, 2)),
        {},
        "test",
    )
    targeted = extract_difficult_neighborhood(problem, seed, bottleneck, neighborhood_size=2)
    global_area = extract_difficult_neighborhood(
        problem, seed, bottleneck, neighborhood_size=10, mode="global_baseline"
    )
    assert len(targeted.positions_for(0)) <= 2
    assert len(targeted.positions_for(0)) <= len(global_area.positions_for(0))


def test_candidate_generation_has_stable_no_change_and_is_deduplicated() -> None:
    problem = cvrp_problem()
    seed = Solution({"0": [0, 1, 2, 3, 0]})
    bottleneck = detect_bottlenecks(problem, seed)[0]
    neighborhood = extract_difficult_neighborhood(problem, seed, bottleneck)
    moves, _rejected = generate_candidate_moves(problem, seed, neighborhood, max_candidates=20)
    assert moves[0].move_id == "m0_no_change"
    assert len({move.move_id for move in moves}) == len(moves)


def test_two_opt_keeps_sdvrp_delivery_positions_aligned() -> None:
    problem = sdvrp_problem()
    seed = sdvrp_seed()
    move = MoveCandidate(
        "m_two_opt",
        "two_opt",
        (1, 2),
        (0,),
        (("vehicle", 0), ("start", 1), ("end", 2)),
        0.0,
        None,
        True,
        None,
    )
    result = apply_move(problem, seed, move)
    assert result.routes["0"] == [0, 2, 1, 0]
    assert not validate_solution(problem, result)
    assignment_map = {(a.vehicle_id, a.route_position): a.customer_id for a in result.deliveries}
    assert assignment_map[(0, 1)] == 2
    assert assignment_map[(0, 2)] == 1


def test_split_merge_updates_routes_and_quantities() -> None:
    problem = sdvrp_problem()
    seed = sdvrp_seed()
    move = MoveCandidate(
        "merge",
        "split_merge",
        (1,),
        (0, 1),
        (
            ("source_vehicle", 1),
            ("source_position", 1),
            ("target_vehicle", 0),
            ("target_position", 1),
            ("quantity", 1.0),
        ),
        0.0,
        None,
        True,
        None,
    )
    result = apply_move(problem, seed, move)
    assert result.routes["1"] == [0, 0]
    assert not validate_solution(problem, result)
    quantities = {(a.vehicle_id, a.route_position, a.customer_id): a.quantity for a in result.deliveries}
    assert quantities[(0, 1, 1)] == pytest.approx(2.0)


def test_improvement_gate_never_degrades() -> None:
    problem = cvrp_problem()
    initial = evaluate_solution(problem, Solution({"0": [0, 1, 2, 3, 0]}))
    better = evaluate_solution(problem, Solution({"0": [0, 3, 1, 2, 0]}))
    selected, accepted, reason = improvement_gate(initial, better)
    assert accepted
    assert reason == "accepted_improvement"
    assert selected.cost < initial.cost

    selected, accepted, _reason = improvement_gate(initial, initial)
    assert not accepted
    assert selected == initial


def test_classical_end_to_end_never_degrades() -> None:
    result = run_quasar_qaoa_xy_hybrid(
        {
            "matrix": cvrp_problem().matrix.tolist(),
            "demands": [0, 1, 1, 1],
            "capacities": [3],
            "starting_nodes": [0],
            "problem_type": "cvrp",
            "routes": {"0": [0, 1, 2, 3, 0]},
            "executor": "classical",
            "polishing_iterations": 5,
        }
    )
    assert result["final_cost"] <= result["initial_cost"] + 1e-9
    assert result["execution_error"] is None
    assert result["bitstring"] is None
    assert result["feasible_sample_rate"] is None


def test_sdvrp_end_to_end_split_merge() -> None:
    result = run_quasar_qaoa_xy_hybrid(
        {
            "matrix": sdvrp_problem().matrix.tolist(),
            "demands": [0, 2, 1],
            "capacities": [3, 2],
            "starting_nodes": [0, 0],
            "problem_type": "sdvrp",
            "routes": sdvrp_seed().routes,
            "deliveries": [assignment.__dict__ for assignment in sdvrp_seed().deliveries],
            "executor": "classical",
            "capacity_pressure_threshold": 1.0,
            "polishing_iterations": 5,
        }
    )
    assert result["final_cost"] <= result["initial_cost"] + 1e-9
    assert result["valid"]


def test_local_executor_reports_missing_qiskit_without_degradation() -> None:
    if importlib.util.find_spec("qiskit") is not None:
        pytest.skip("This test targets the dependency-missing fallback.")
    result = run_quasar_qaoa_xy_hybrid(
        {
            "matrix": [[0, 1, 2], [1, 0, 1], [2, 1, 0]],
            "demands": [0, 1, 1],
            "capacities": [2],
            "starting_nodes": [0],
            "problem_type": "cvrp",
            "routes": {"0": [0, 2, 1, 0]},
            "executor": "local",
        }
    )
    assert result["acceptance_reason"] == "quantum_execution_failed"
    assert result["final_cost"] == result["initial_cost"]
    assert "qiskit" in result["execution_error"].lower()


def test_hamiltonian_bit_order_and_exact_one_energy_without_qiskit() -> None:
    hamiltonian = CandidateHamiltonian(
        operator=None,
        candidate_costs=(0.0, -2.0, 1.0),
        one_hot_penalty=10.0,
        pairwise_interactions=((0.0, 7.0, 0.0), (7.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        candidate_to_qubit=(("m0_no_change", 0), ("m1", 1), ("m2", 2)),
        qubit_to_candidate=("m0_no_change", "m1", "m2"),
    )
    assert decode_one_hot_bitstring("010", 3) == 1
    assert evaluate_bitstring_energy("010", hamiltonian) == pytest.approx(-2.0)
    states = brute_force_exact_one(hamiltonian)
    assert states[0] == ("010", -2.0)
    # Pairwise terms do not affect valid exact-one states.
    assert evaluate_bitstring_energy("100", hamiltonian) == pytest.approx(1.0)


@pytest.mark.skipif(importlib.util.find_spec("qiskit") is None, reason="Qiskit is not installed")
def test_xy_mixer_preserves_hamming_weight() -> None:
    from qiskit.quantum_info import SparsePauliOp, Statevector

    from app.services.quantum_hybrid.warm_start import build_qaoa_xy_circuit

    operator = SparsePauliOp.from_list([("III", 0.0)])
    circuit, order = build_qaoa_xy_circuit(operator, 1, initialization="no-op", xy_topology="ring")
    bound = circuit.assign_parameters({order[0]: 0.3, order[1]: 0.7})
    probabilities = Statevector.from_instruction(bound).probabilities_dict()
    assert sum(prob for bitstring, prob in probabilities.items() if bitstring.count("1") != 1) < 1e-10
