import asyncio
import time
import json
import sys
from pathlib import Path
import os
from uuid import uuid4
from datetime import datetime, UTC

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.messaging.models import DomainEvent, EVENT_WEATHER_OBSERVED, create_weather_observed_event
from app.messaging.sqs.publisher import SqsEventPublisher
from app.messaging.sqs.consumer import SqsEventConsumer
from app.messaging.consumer import HandlerRegistry, DomainEventHandler
from app.messaging.idempotency import RedisIdempotencyStore
from app.messaging.metrics import MessagingMetrics

from app.messaging.sqs.client import InMemorySqsTransport

class _FakeRedis:
    def __init__(self):
        self.keys = set()
    async def set(self, key, value, nx=False, px=None, ex=None):
        if nx and key in self.keys: return None
        self.keys.add(key)
        return True
    async def get(self, key):
        return key if key in self.keys else None
    async def delete(self, key):
        self.keys.discard(key)
        return 1
    async def eval(self, script, numkeys, *args):
        return 1

class NoOpHandler(DomainEventHandler):
    async def handle(self, event: DomainEvent) -> None:
        pass

async def run_benchmarks():
    print("=== Event Processing Throughput Benchmark ===")
    
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/benchmark"
    metrics = MessagingMetrics()
    store = RedisIdempotencyStore(_FakeRedis())
    
    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, NoOpHandler())
    
    publisher = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)
    
    results = []
    concurrency_levels = [1, 5, 10, 20]
    num_events = 1000
    
    # Generate payloads
    events = []
    for i in range(num_events):
        events.append(create_weather_observed_event(
            latitude=float(i),
            longitude=float(i),
            rainfall_rate_mm_h=10.0,
        ))
        
    for concurrency in concurrency_levels:
        transport.queues.clear()
        
        consumer = SqsEventConsumer(
            client=transport,
            queue_url=queue_url,
            registry=registry,
            idempotency_store=store,
            metrics=metrics,
            concurrency=concurrency,
            max_messages=10,
            wait_time_seconds=0
        )
        
        # Publish phase
        t0 = time.perf_counter()
        for evt in events:
            await publisher.publish(evt)
        pub_time = time.perf_counter() - t0
        
        # Consume phase
        t1 = time.perf_counter()
        processed = 0
        while transport.get_queue_length(queue_url) > 0:
            processed += await consumer.poll_once()
        cons_time = time.perf_counter() - t1
        
        pub_rate = num_events / pub_time if pub_time > 0 else 0
        cons_rate = num_events / cons_time if cons_time > 0 else 0
        
        print(f"Concurrency: {concurrency:2d} | Publish: {pub_rate:6.0f} evt/s | Consume: {cons_rate:6.0f} evt/s | Pub time: {pub_time*1000:.1f}ms | Cons time: {cons_time*1000:.1f}ms")
        
        results.append({
            "transport": "InMemory",
            "concurrency": concurrency,
            "events": num_events,
            "publish_rate_eps": pub_rate,
            "consume_rate_eps": cons_rate,
            "publish_time_ms": pub_time * 1000,
            "consume_time_ms": cons_time * 1000
        })
        
    out_dir = Path(__file__).resolve().parent.parent / "performance" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "messaging.json", "w") as f:
        json.dump({"runs": results}, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_benchmarks())
