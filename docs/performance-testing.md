# FloodGuard Performance Testing Architecture

## Overview
Phase 23 establishes the performance testing and baselining capabilities for the FloodGuard application. Rather than rewriting working code, this phase focuses on rigorous, reproducible, and evidence-based measurements.

## Core Benchmark Suites

1. **Routing Benchmark**
   - Measures A* vs Dijkstra execution times across grid graphs of varying dimensions (10x10 to 100x100).
   - Validates node expansion efficiency (A* heuristics) vs raw execution latency.

2. **Cache Benchmark**
   - Tests cold start (MISS) vs warm cache (HIT) latencies using `InMemoryFakeRedis`.
   - Validates the overall speedup achieved by the caching layer for route calculation.

3. **Event Processing Benchmark**
   - Validates publish and consume rates for `InMemorySqsTransport`.
   - Determines peak throughput scaling under various concurrency limits (1 to 20 concurrent consumer workers).

4. **Real-time Rerouting Benchmark**
   - Evaluates the impact of simultaneous recalculation when active routes are invalidated by risk events.

5. **SSE Broadcasting Benchmark**
   - Estimates asyncio-based single-node broadcast limits for SSE clients.

## Workload Profiles

- **Profile A (Local/Micro)**: Small synthetic graphs and low concurrency. Good for quick verification.
- **Profile B (Medium/Load)**: Medium graph scale, cache stress, and normal concurrency.
- **Profile C (Burst)**: High event publishing/consuming throughput testing simulating environmental bursts.

## How to Run

A set of benchmark scripts are located in `scripts/`:

```bash
uv run python scripts/benchmark_routing.py
uv run python scripts/benchmark_cache.py
uv run python scripts/benchmark_events.py
uv run python scripts/benchmark_rerouting.py
uv run python scripts/benchmark_sse.py
```

Results are uniformly captured in `performance/reports/*.json`.
