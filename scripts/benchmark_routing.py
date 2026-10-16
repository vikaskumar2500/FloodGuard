import time
import json
import uuid
import random
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.routing.models import RoutingGraph, RoutingNode, RoutingEdge
from app.routing.dijkstra import find_path as find_path_dijkstra
from app.routing.astar import find_path as find_path_astar

def generate_grid_graph(size: int, seed: int = 42) -> RoutingGraph:
    random.seed(seed)
    graph = RoutingGraph()
    nodes = {}
    
    # Create size x size grid
    for y in range(size):
        for x in range(size):
            node_id = uuid.uuid4()
            node = RoutingNode(id=node_id, coordinate=(float(x) * 0.01, float(y) * 0.01))
            nodes[(x, y)] = node
            graph.add_node(node)
            
    # Create edges
    for y in range(size):
        for x in range(size):
            u_coord = (x, y)
            u = nodes[u_coord]
            
            # Connect right
            if x < size - 1:
                v_coord = (x + 1, y)
                v = nodes[v_coord]
                edge_id = uuid.uuid4()
                edge = RoutingEdge(
                    id=edge_id,
                    source=u.id,
                    target=v.id,
                    distance_m=1000.0,
                    base_travel_time_s=100.0,
                    geometry=(u.coordinate, v.coordinate)
                )
                graph.add_edge(edge)
            
            # Connect down
            if y < size - 1:
                v_coord = (x, y + 1)
                v = nodes[v_coord]
                edge_id = uuid.uuid4()
                edge = RoutingEdge(
                    id=edge_id,
                    source=u.id,
                    target=v.id,
                    distance_m=1000.0,
                    base_travel_time_s=100.0,
                    geometry=(u.coordinate, v.coordinate)
                )
                graph.add_edge(edge)
                
    return graph, nodes[(0,0)].id, nodes[(size-1, size-1)].id

def calculate_percentiles(times):
    times.sort()
    count = len(times)
    return {
        "median": times[count // 2],
        "p95": times[int(count * 0.95)] if count >= 20 else max(times),
        "min": times[0],
        "max": times[-1]
    }

def run_benchmarks():
    sizes = [10, 31, 100] # 10x10=100, 31x31~1000, 100x100=10000 nodes
    results = []
    
    print("=== Routing Algorithm Benchmark ===")
    for s in sizes:
        print(f"Generating graph {s}x{s}...")
        t0 = time.perf_counter()
        graph, start_id, end_id = generate_grid_graph(s)
        gen_time = time.perf_counter() - t0
        node_count = len(graph.nodes)
        edge_count = len(graph.edges)
        print(f"Graph loaded in {gen_time*1000:.2f}ms. Nodes: {node_count}, Edges: {edge_count}")
        
        costs = {e.id: e.base_travel_time_s for e in graph.edges.values()}
        
        # Warmup
        for _ in range(3):
            find_path_dijkstra(graph, start_id, end_id, max_expansions=100000, costs=costs)
            find_path_astar(graph, start_id, end_id, max_expansions=100000, costs=costs)
            
        iterations = 10 if s == 100 else 50
        
        # Dijkstra
        d_times = []
        d_expansions = 0
        d_cost = 0
        for _ in range(iterations):
            t1 = time.perf_counter()
            path = find_path_dijkstra(graph, start_id, end_id, max_expansions=1000000, costs=costs)
            d_times.append((time.perf_counter() - t1) * 1000)
            d_expansions = path.expanded_nodes
            d_cost = path.total_cost
            
        d_metrics = calculate_percentiles(d_times)
        
        # A*
        a_times = []
        a_expansions = 0
        a_cost = 0
        for _ in range(iterations):
            t1 = time.perf_counter()
            path = find_path_astar(graph, start_id, end_id, max_expansions=1000000, costs=costs)
            a_times.append((time.perf_counter() - t1) * 1000)
            a_expansions = path.expanded_nodes
            a_cost = path.total_cost
            
        a_metrics = calculate_percentiles(a_times)
        
        print(f"Graph Size: {node_count} nodes")
        print(f"Dijkstra | Cost: {d_cost:.1f} | Expanded: {d_expansions} | Median: {d_metrics['median']:.2f}ms | p95: {d_metrics['p95']:.2f}ms")
        print(f"A*       | Cost: {a_cost:.1f} | Expanded: {a_expansions} | Median: {a_metrics['median']:.2f}ms | p95: {a_metrics['p95']:.2f}ms")
        print("-" * 50)
        
        assert abs(d_cost - a_cost) < 0.001, "Path costs differ between algorithms"
        
        results.append({
            "nodes": node_count,
            "edges": edge_count,
            "dijkstra": {
                "median_ms": d_metrics["median"],
                "p95_ms": d_metrics["p95"],
                "expanded": d_expansions
            },
            "astar": {
                "median_ms": a_metrics["median"],
                "p95_ms": a_metrics["p95"],
                "expanded": a_expansions
            }
        })
        
    out_dir = Path(__file__).resolve().parent.parent / "performance" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "routing.json", "w") as f:
        json.dump({"runs": results, "metadata": {"iterations_base": 50}}, f, indent=2)

if __name__ == "__main__":
    run_benchmarks()
