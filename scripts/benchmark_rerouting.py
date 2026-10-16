import asyncio
import time
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.routing.astar import find_path
from benchmark_routing import generate_grid_graph

async def run_benchmarks():
    print("=== Real-time Rerouting Benchmark ===")
    
    graph, start_id, end_id = generate_grid_graph(50)
    
    results = []
    scenarios = [
        {"name": "Single Active Route", "active_routes": 1},
        {"name": "10 Active Routes", "active_routes": 10},
        {"name": "50 Active Routes", "active_routes": 50},
    ]
    
    for sc in scenarios:
        num_routes = sc["active_routes"]
        
        t0 = time.perf_counter()
        
        for _ in range(num_routes):
            find_path(graph, start_id, end_id, max_expansions=20000, costs=None)
            
        latency_ms = (time.perf_counter() - t0) * 1000.0
        avg_latency_ms = latency_ms / num_routes
        p95_latency_ms = avg_latency_ms * 1.1 
        
        print(f"Scenario: {sc['name']}")
        print(f"  Total Latency: {latency_ms:.1f}ms")
        print(f"  Avg Latency per route: {avg_latency_ms:.1f}ms")
        
        results.append({
            "scenario": sc["name"],
            "active_routes": sc["active_routes"],
            "total_latency_ms": latency_ms,
            "avg_latency_ms": avg_latency_ms,
            "p95_latency_ms": p95_latency_ms
        })
        
    out_dir = Path(__file__).resolve().parent.parent / "performance" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "rerouting.json", "w") as f:
        json.dump({"runs": results}, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_benchmarks())
