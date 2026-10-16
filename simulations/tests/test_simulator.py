from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

import pytest

from simulations.clock import SimulationClock
from simulations.engine import generate_events, seeded_scenario
from simulations.integration import events_to_evidence, route_with_simulated_risk
from simulations.models import EventType, ScenarioDefinition, ScenarioStep, SimulationEvent
from simulations.replay import read_events
from simulations.sinks.memory import MemorySink

NAMESPACE = UUID("ee40f1cf-88c2-4b61-8c36-b7c2e5f9f6f2")
START = datetime(2026, 10, 7, tzinfo=UTC)


def test_flash_flood_is_repeatable_for_same_seed_and_start():
    first_sink = MemorySink()
    second_sink = MemorySink()
    scenario = seeded_scenario("flash_flood", 42)
    first = generate_events(scenario, seed=42, clock=SimulationClock(START), sink=first_sink)
    second = generate_events(scenario, seed=42, clock=SimulationClock(START), sink=second_sink)

    assert [event.to_dict() for event in first.events] == [
        event.to_dict() for event in second.events
    ]
    assert len(first.events) == 8
    assert first.events[-1].occurred_at == START + timedelta(minutes=25)


def test_all_scenarios_generate_valid_ordered_events():
    for name in (
        "normal",
        "moderate_rain",
        "severe_rain",
        "flash_flood",
        "sensor_outage",
        "recovery",
    ):
        result = generate_events(
            seeded_scenario(name, 7),
            seed=7,
            clock=SimulationClock(START),
        )
        assert [event.sequence for event in result.events] == list(range(len(result.events)))
        assert list(event.occurred_at for event in result.events) == sorted(
            event.occurred_at for event in result.events
        )


def test_file_sink_round_trip_and_duplicate_delivery(tmp_path):
    from simulations.sinks.file import FileSink

    event = SimulationEvent.create(
        "test-1",
        0,
        EventType.RAINFALL_OBSERVATION,
        START,
        {"rainfall_mm_per_hour": 4, "unit": "mm/hour"},
    )
    path = tmp_path / "events.jsonl"
    sink = FileSink(path)
    sink.emit(event)
    sink.emit(event)
    sink.close()

    replayed = read_events(path)
    assert len(replayed) == 1
    assert replayed[0].event_id == event.event_id


def test_invalid_event_measurement_is_rejected():
    scenario = ScenarioDefinition(
        "invalid",
        "invalid",
        timedelta(minutes=1),
        (
            ScenarioStep(
                timedelta(0),
                EventType.WATER_DEPTH_READING,
                {"water_depth_cm": -1, "unit": "cm"},
            ),
        ),
    )
    with pytest.raises(ValueError):
        generate_events(scenario, seed=1, clock=SimulationClock(START))


def test_memory_sink_deduplicates_events():
    event = SimulationEvent.create("test-2", 0, EventType.RAINFALL_OBSERVATION, START, {})
    sink = MemorySink()
    sink.emit(event)
    sink.emit(event)

    assert len(sink.events) == 1
    assert sink.duplicates_ignored == 1


def test_sensor_outage_removes_readings_and_confidence():
    from app.risk.config import RiskConfig
    from app.risk.service import evaluate_graph
    from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode

    edge_id = uuid5(NAMESPACE, "outage-edge")
    source = uuid5(NAMESPACE, "outage-source")
    target = uuid5(NAMESPACE, "outage-target")
    graph = RoutingGraph()
    graph.add_node(RoutingNode(source, (0.0, 0.0)))
    graph.add_node(RoutingNode(target, (0.001, 0.0)))
    graph.add_edge(RoutingEdge(edge_id, source, target, 1, 1, ((0.0, 0.0), (0.001, 0.0))))
    graph.validate()
    events = generate_events(
        seeded_scenario("sensor_outage", 42), seed=42, clock=SimulationClock(START)
    ).events
    aliases = {"fixture-top-1": edge_id, "fixture-top-2": edge_id, "fixture-top-3": edge_id}
    before = events_to_evidence(events, aliases, START + timedelta(minutes=10))
    after = events_to_evidence(events, aliases, START + timedelta(minutes=20))
    before_snapshot = evaluate_graph(graph, before, START + timedelta(minutes=10), RiskConfig())
    after_snapshot = evaluate_graph(graph, after, START + timedelta(minutes=20), RiskConfig())

    assert before[edge_id].sensors
    assert not after[edge_id].sensors
    assert (
        before_snapshot.assessments[edge_id].confidence
        > after_snapshot.assessments[edge_id].confidence
    )


def test_flash_flood_changes_risk_and_recovery_reduces_it():
    from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode

    graph = RoutingGraph()
    nodes = {name: uuid5(NAMESPACE, f"node-{name}") for name in "ABCDEF"}
    coordinates = {
        "A": (0.0, 0.0),
        "B": (0.001, 0.0),
        "C": (0.002, 0.0),
        "D": (0.003, 0.0),
        "E": (0.0, 0.001),
        "F": (0.0015, 0.001),
    }
    for name, coordinate in coordinates.items():
        graph.add_node(RoutingNode(nodes[name], coordinate))
    aliases = {}
    for index, (source, target) in enumerate(zip("ABC", "BCD", strict=True), 1):
        edge_id = uuid5(NAMESPACE, f"edge-{index}")
        aliases[f"fixture-top-{index}"] = edge_id
        graph.add_edge(
            RoutingEdge(
                edge_id,
                nodes[source],
                nodes[target],
                1,
                1,
                (coordinates[source], coordinates[target]),
            )
        )
    for index, (source, target) in enumerate(zip("AEF", "EFD", strict=True), 1):
        graph.add_edge(
            RoutingEdge(
                uuid5(NAMESPACE, f"lower-edge-{index}"),
                nodes[source],
                nodes[target],
                2,
                2,
                (coordinates[source], coordinates[target]),
            )
        )
    graph.validate()
    result = generate_events(
        seeded_scenario("flash_flood", 42), seed=42, clock=SimulationClock(START)
    )
    before_path, before, _ = route_with_simulated_risk(
        graph,
        nodes["A"],
        nodes["D"],
        result.events,
        aliases,
        START,
        "SAFEST",
        "DIJKSTRA",
    )
    during_path, during, during_snapshot = route_with_simulated_risk(
        graph,
        nodes["A"],
        nodes["D"],
        result.events,
        aliases,
        START + timedelta(minutes=20),
        "SAFEST",
        "DIJKSTRA",
    )
    recovery = generate_events(
        seeded_scenario("recovery", 42), seed=42, clock=SimulationClock(START)
    )
    _, recovered, recovery_snapshot = route_with_simulated_risk(
        graph,
        nodes["A"],
        nodes["D"],
        recovery.events,
        aliases,
        START + timedelta(minutes=30),
        "SAFEST",
        "DIJKSTRA",
    )

    assert before.risk_score == 0
    assert during.risk_score <= before.risk_score
    assert during_snapshot.assessments[aliases["fixture-top-1"]].risk_score > 0
    assert (
        recovery_snapshot.assessments[aliases["fixture-top-1"]].risk_score
        < during_snapshot.assessments[aliases["fixture-top-1"]].risk_score
    )
    assert before_path.node_ids == (nodes["A"], nodes["B"], nodes["C"], nodes["D"])
    assert during_path.node_ids == (nodes["A"], nodes["E"], nodes["F"], nodes["D"])
