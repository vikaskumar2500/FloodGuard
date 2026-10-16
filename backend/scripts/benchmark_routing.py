import json
import statistics
import time
from pathlib import Path
from uuid import UUID, uuid5

from app.ingestion.osm.service import load_graph
from app.routing.astar import find_path as astar
from app.routing.dijkstra import find_path as dijkstra
from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode

NAMESPACE = UUID("7a1d88f0-6e4c-4d1b-b45f-6e8e3696e415")


def graph_from_fixture() -> tuple[RoutingGraph, UUID, UUID]:
    imported, _ = load_graph(Path(__file__).parents[1] / "tests" / "fixtures" / "tiny.osm")
    graph = RoutingGraph()
    ids = {node.osm_id: uuid5(NAMESPACE, f"node-{node.osm_id}") for node in imported.nodes}
    for node in imported.nodes:
        graph.add_node(RoutingNode(ids[node.osm_id], node.coordinate))
    for index, edge in enumerate(imported.edges):
        graph.add_edge(
            RoutingEdge(
                uuid5(NAMESPACE, f"edge-{index}"),
                ids[edge.source_osm_node_id],
                ids[edge.target_osm_node_id],
                edge.distance_m,
                edge.base_travel_time_s,
                edge.coordinates,
                edge.distance_m / edge.base_travel_time_s,
            )
        )
    graph.validate()
    return graph, ids[1], ids[6]


def benchmark(search, graph, source, destination, runs: int) -> dict:
    durations = []
    result = None
    for _ in range(runs):
        started = time.perf_counter()
        result = search(graph, source, destination)
        durations.append((time.perf_counter() - started) * 1000)
    assert result is not None
    return {
        "found": result.found,
        "cost_seconds": result.total_cost,
        "expanded_nodes": result.expanded_nodes,
        "median_ms": statistics.median(durations),
        "runs": runs,
    }


def main() -> None:
    graph, source, destination = graph_from_fixture()
    print(
        json.dumps(
            {
                "graph_nodes": len(graph.nodes),
                "graph_edges": len(graph.edges),
                "source": str(source),
                "destination": str(destination),
                "dijkstra": benchmark(dijkstra, graph, source, destination, 20),
                "astar": benchmark(astar, graph, source, destination, 20),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
