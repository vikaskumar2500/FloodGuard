import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .engine import build_clock, generate_events, seeded_scenario
from .replay import read_events, replay_events
from .scenarios import available_scenarios
from .sinks import BackendSink, FileSink, MemorySink

DEFAULT_START = datetime(2026, 10, 7, tzinfo=UTC)


def parse_start(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("start time must include a timezone")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulations", description="FloodGuard deterministic simulator"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    run = commands.add_parser("run")
    run.add_argument(
        "--scenario",
        required=True,
        type=str.upper,
        choices=available_scenarios(),
    )
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--start-time", type=parse_start, default=DEFAULT_START)
    run.add_argument("--mode", choices=("immediate", "timed"), default="immediate")
    run.add_argument("--speed", type=float, default=1.0)
    run.add_argument("--sink", choices=("memory", "file", "backend", "sqs", "eventbridge"), default="memory")
    run.add_argument("--output", type=Path)
    run.add_argument("--endpoint", default=None)
    run.add_argument("--backend-url", default=None)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--verbose", action="store_true")
    replay = commands.add_parser("replay")
    replay.add_argument("--file", required=True, type=Path)
    replay.add_argument("--output", type=Path)
    return parser


def print_summary(result) -> None:
    print(
        json.dumps(
            {
                "scenario": result.scenario.name,
                "seed": result.seed,
                "simulation_duration_minutes": result.scenario.duration.total_seconds() / 60,
                "events_generated": len(result.events),
                "event_counts": result.counts,
                "duplicates_ignored": result.duplicates_ignored,
            },
            indent=2,
            sort_keys=True,
        )
    )


def run_command(args: argparse.Namespace) -> None:
    scenario = seeded_scenario(args.scenario, args.seed)
    sink = None
    if not args.dry_run:
        if args.sink == "memory":
            sink = MemorySink()
        elif args.sink == "file":
            if args.output is None:
                raise SystemExit("--output is required for the file sink")
            sink = FileSink(args.output)
        elif args.sink in {"sqs", "eventbridge"}:
            from app.core.config import Settings
            from app.messaging.factory import create_event_publisher
            from simulations.sinks.sqs import SqsSimulationSink

            settings = Settings(
                event_transport=args.sink.upper(), sqs_enabled=True,
                eventbridge_enabled=args.sink == "eventbridge",
            )
            sink = SqsSimulationSink(create_event_publisher(settings))
        else:
            endpoint = args.endpoint
            if not endpoint and args.backend_url:
                endpoint = f"{args.backend_url.rstrip('/')}/api/v1/dev/simulation/events"
            elif not endpoint:
                endpoint = "http://localhost:8000/api/v1/dev/simulation/events"
            sink = BackendSink(endpoint)
    clock = build_clock(args.start_time, args.mode, args.speed)
    result = generate_events(scenario, seed=args.seed, clock=clock, sink=sink)
    if sink is not None:
        sink.close()
    if args.verbose:
        for event in result.events:
            print(f"{event.occurred_at.isoformat()} {event.event_type.value} {event.payload}")
    print_summary(result)


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "list":
        for scenario in available_scenarios():
            print(scenario)
        return
    if args.command == "run":
        run_command(args)
        return
    events = read_events(args.file)
    sink = FileSink(args.output) if args.output else MemorySink()
    replay_events(events, sink)
    print(json.dumps({"events_replayed": len(events), "source": str(args.file)}, indent=2))


if __name__ == "__main__":
    main()
