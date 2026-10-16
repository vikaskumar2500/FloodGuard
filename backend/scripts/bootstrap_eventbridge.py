"""Render/apply Phase 15 resources for an EXISTING Standard SQS queue; never run at startup."""

import argparse
import json

from app.messaging.eventbridge.rules import processing_rules


def resource_spec(bus_name: str, source: str, queue_arn: str) -> dict:
    parts = queue_arn.split(":")
    if len(parts) != 6 or parts[2] != "sqs" or not parts[3] or not parts[4]:
        raise ValueError("Expected an explicit SQS queue ARN")
    if "*" in queue_arn or parts[5].endswith(".fifo"):
        raise ValueError("Use one explicit Standard queue ARN")
    if not bus_name or bus_name == "default" or ":" in bus_name or "/" in bus_name:
        raise ValueError("Provision a custom bus NAME (publisher also accepts ARN)")
    partition, region, account = parts[1], parts[3], parts[4]
    bus_arn = f"arn:{partition}:events:{region}:{account}:event-bus/{bus_name}"
    rules, statements = [], []
    for name, pattern in processing_rules(source).items():
        rule_arn = f"arn:{partition}:events:{region}:{account}:rule/{bus_name}/{name}"
        rules.append(
            {
                "Name": name,
                "EventBusName": bus_name,
                "State": "ENABLED",
                "EventPattern": pattern,
                "Targets": [{"Id": "processing-sqs", "Arn": queue_arn}],
            }
        )
        statements.append(
            {
                "Sid": name.replace("-", ""),
                "Effect": "Allow",
                "Principal": {"Service": "events.amazonaws.com"},
                "Action": "sqs:SendMessage",
                "Resource": queue_arn,
                "Condition": {"ArnEquals": {"aws:SourceArn": rule_arn}},
            }
        )
    return {
        "EventBus": {"Name": bus_name},
        "Rules": rules,
        "QueuePolicy": {"Version": "2012-10-17", "Statement": statements},
        "ProducerPolicy": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "events:PutEvents",
                    "Resource": bus_arn,
                }
            ],
        },
        "ConsumerPolicy": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage",
                        "sqs:ChangeMessageVisibility",
                        "sqs:GetQueueUrl",
                        "sqs:GetQueueAttributes",
                    ],
                    "Resource": queue_arn,
                }
            ],
        },
    }


def apply_spec(spec: dict, events, sqs, queue_url: str) -> None:
    bus = spec["EventBus"]["Name"]
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["QueueArn", "Policy"],
    )["Attributes"]
    if attributes["QueueArn"] != spec["Rules"][0]["Targets"][0]["Arn"]:
        raise ValueError("Queue URL and ARN do not identify the same queue")
    try:
        events.describe_event_bus(Name=bus)
    except events.exceptions.ResourceNotFoundException:
        events.create_event_bus(Name=bus)
    for rule in spec["Rules"]:
        events.put_rule(
            **{
                k: json.dumps(v) if k == "EventPattern" else v
                for k, v in rule.items()
                if k != "Targets"
            }
        )
    # Preserve unrelated permissions; replace only the three owned statements by Sid.
    policy = json.loads(attributes.get("Policy", '{"Version":"2012-10-17","Statement":[]}'))
    owned = spec["QueuePolicy"]["Statement"]
    sids = {s["Sid"] for s in owned}
    policy["Statement"] = [
        s for s in policy.get("Statement", []) if s.get("Sid") not in sids
    ] + owned
    sqs.set_queue_attributes(QueueUrl=queue_url, Attributes={"Policy": json.dumps(policy)})
    for rule in spec["Rules"]:
        result = events.put_targets(EventBusName=bus, Rule=rule["Name"], Targets=rule["Targets"])
        if result.get("FailedEntryCount", 0):
            raise RuntimeError(f"PutTargets failed for {rule['Name']}: {result['FailedEntries']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-name", default="floodguard-dev-events")
    parser.add_argument("--source", default="com.floodguard")
    parser.add_argument("--queue-arn", required=True)
    parser.add_argument("--queue-url")
    parser.add_argument("--endpoint-url")
    parser.add_argument("--apply", action="store_true", help="Apply; default only prints JSON")
    args = parser.parse_args()
    spec = resource_spec(args.bus_name, args.source, args.queue_arn)
    if not args.apply:
        print(json.dumps(spec, indent=2))
        return
    if not args.queue_url:
        parser.error("--apply requires --queue-url")
    import boto3

    region = args.queue_arn.split(":")[3]
    apply_spec(
        spec,
        boto3.client("events", region_name=region, endpoint_url=args.endpoint_url),
        boto3.client("sqs", region_name=region, endpoint_url=args.endpoint_url),
        args.queue_url,
    )
    print(f"Configured {args.bus_name} with three rules targeting the existing SQS queue")


if __name__ == "__main__":
    main()
