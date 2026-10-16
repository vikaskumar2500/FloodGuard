import asyncio
import time
import json
from pathlib import Path

class MockSseManager:
    def __init__(self):
        self.clients = []
    
    def connect(self, num_clients):
        self.clients = [asyncio.Queue() for _ in range(num_clients)]
        
    async def broadcast(self, message: str):
        # Broadcast simulates iterating over clients and putting messages in their queues
        for q in self.clients:
            q.put_nowait(message)

async def run_benchmarks():
    print("=== SSE Publishing Benchmark ===")
    
    manager = MockSseManager()
    
    results = []
    scenarios = [
        {"name": "100 Concurrent Clients", "clients": 100},
        {"name": "1000 Concurrent Clients", "clients": 1000},
        {"name": "5000 Concurrent Clients", "clients": 5000},
    ]
    
    for sc in scenarios:
        num_clients = sc["clients"]
        manager.connect(num_clients)
        
        t0 = time.perf_counter()
        
        # broadcast 100 times to get a stable average
        num_broadcasts = 100
        for _ in range(num_broadcasts):
            await manager.broadcast('{"event": "route_invalidated"}')
            
        total_latency_ms = (time.perf_counter() - t0) * 1000.0
        avg_latency_ms = total_latency_ms / num_broadcasts
        
        print(f"Scenario: {sc['name']}")
        print(f"  Broadcast Latency: {avg_latency_ms:.3f}ms")
        
        results.append({
            "scenario": sc["name"],
            "clients": sc["clients"],
            "broadcast_latency_ms": avg_latency_ms
        })
        
    out_dir = Path(__file__).resolve().parent.parent / "performance" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "sse.json", "w") as f:
        json.dump({"runs": results}, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_benchmarks())
