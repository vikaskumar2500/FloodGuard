import json
from pathlib import Path

from .models import SimulationEvent
from .sinks.base import SimulationSink


def read_events(path: Path) -> tuple[SimulationEvent, ...]:
    events = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                events.append(SimulationEvent.from_dict(json.loads(line)))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid simulation event at line {line_number}") from error
    validate_recording(events)
    return tuple(events)


def validate_recording(events: tuple[SimulationEvent, ...]) -> None:
    event_ids = [event.event_id for event in events]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("recording contains duplicate event IDs")
    sequences = [event.sequence for event in events]
    if sequences != sorted(sequences) or sequences != list(range(len(sequences))):
        raise ValueError("recording sequences must be contiguous and ordered")
    timestamps = [event.occurred_at for event in events]
    if timestamps != sorted(timestamps):
        raise ValueError("recording timestamps must be nondecreasing")


def replay_events(events: tuple[SimulationEvent, ...], sink: SimulationSink) -> int:
    for event in events:
        sink.emit(event)
    sink.close()
    return len(events)
