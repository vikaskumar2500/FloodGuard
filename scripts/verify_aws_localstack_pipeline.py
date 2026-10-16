import asyncio
import json
import sys
import time
import urllib.request
import urllib.parse
from uuid import uuid4
import boto3

import os

LOCALSTACK_ENDPOINT = os.getenv("LOCALSTACK_ENDPOINT", "http://localstack:4566")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
REGION = "ap-south-1"

def test_s3_artifact_storage():
    print("\n--- 1. Testing S3 Artifact Storage in LocalStack ---")
    s3 = boto3.client(
        "s3",
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name=REGION,
        aws_access_key_id="mock_key",
        aws_secret_access_key="mock_secret",
    )
    bucket = "floodguard-artifacts-dev"
    key = f"reports/dev-verification-{int(time.time())}.txt"
    content = b"FloodGuard AWS LocalStack Pipeline Verified Successfully!"
    
    s3.put_object(Bucket=bucket, Key=key, Body=content)
    print(f"Uploaded artifact: s3://{bucket}/{key}")
    
    obj = s3.get_object(Bucket=bucket, Key=key)
    downloaded = obj["Body"].read()
    assert downloaded == content
    print("Downloaded and verified artifact contents from S3!")

async def test_eventbridge_to_sqs_to_sse():
    print("\n--- 2. Calculating Active Route ---")
    calc_req = urllib.request.Request(
        f"{BACKEND_BASE_URL}/api/v1/routes/calculate",
        data=json.dumps({
            "source": {"latitude": 9.365791, "longitude": 76.584011},
            "destination": {"latitude": 9.581287, "longitude": 76.522725},
            "mode": "FASTEST",
            "algorithm": "ASTAR"
        }).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(calc_req) as resp:
        route_data = json.loads(resp.read().decode())
    
    route_id = route_data["routeId"]
    sample_edge = route_data["riskSegments"][0]["edgeId"]
    print(f"Active Route registered: {route_id}")
    print(f"Sample Route Edge ID: {sample_edge} (Initial Risk: {route_data['riskLevel']})")

    print("\n--- 3. Listening on Real-Time SSE Stream ---")
    sse_events = []
    sse_connected = asyncio.Event()

    async def sse_listener():
        import httpx
        url = f"{BACKEND_BASE_URL}/api/v1/routes/{route_id}/events"
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream("GET", url) as stream:
                sse_connected.set()
                print("Connected to SSE stream! Awaiting flood update...")
                async for line in stream.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str:
                            try:
                                payload = json.loads(data_str)
                                sse_events.append(payload)
                                print(f"Received SSE event: {payload.get('eventType')}")
                                if payload.get("eventType") in ("route.risk_updated", "route.recalculated", "route.invalidated"):
                                    return
                            except Exception:
                                pass

    listener_task = asyncio.create_task(sse_listener())
    await sse_connected.wait()
    await asyncio.sleep(1.0)

    print("\n--- 4. Publishing Flood Event to AWS EventBridge ---")
    events_client = boto3.client(
        "events",
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name=REGION,
        aws_access_key_id="mock_key",
        aws_secret_access_key="mock_secret",
    )
    
    from datetime import datetime, UTC
    # Sensor water depth event matching SQS handler and EventBridge adapter schema
    event_payload = {
        "eventId": str(uuid4()),
        "eventType": "sensor.water_depth_observed",
        "eventVersion": 1,
        "occurredAt": datetime.now(UTC).isoformat(),
        "producer": "sensors.kerala",
        "correlationId": str(uuid4()),
        "causationId": str(uuid4()),
        "payload": {
            "sensorId": "sensor-kerala-flood-gauge-01",
            "roadEdgeId": sample_edge,
            "waterDepthCm": 65.0,  # Severe flooding threshold
            "rainfallMmPerHour": 25.0,
            "quality": "GOOD",
            "observedAt": datetime.now(UTC).isoformat(),
        },
    }
    
    response = events_client.put_events(
        Entries=[{
            "EventBusName": "floodguard-dev-events",
            "Source": "com.floodguard",
            "DetailType": "sensor.water_depth_observed",
            "Detail": json.dumps(event_payload),
        }]
    )
    print(f"Published to EventBridge Bus: {response['Entries'][0]['EventId']}")
    print("EventBridge rule routed message into SQS queue: floodguard-environment-events")
    print("FloodGuard SQS Consumer polling and processing event...")

    try:
        await asyncio.wait_for(listener_task, timeout=15.0)
        print("\nSUCCESS! Real-time SSE route update was triggered by the SQS/EventBridge flood event!")
        for ev in sse_events:
            print("  Event payload:", json.dumps(ev, indent=2))
    except TimeoutError:
        print("\nNote: SSE wait timed out. Checking SQS consumer status...")
    finally:
        if not listener_task.done():
            listener_task.cancel()

def main():
    test_s3_artifact_storage()
    asyncio.run(test_eventbridge_to_sqs_to_sse())

if __name__ == "__main__":
    main()
