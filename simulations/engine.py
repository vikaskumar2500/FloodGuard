from dataclasses import dataclass
from datetime import datetime
from random import Random

from .clock import SimulationClock
from .models import ScenarioDefinition, SimulationEvent, validate_event
from .sinks.base import SimulationSink


@dataclass(frozen=True)
class SimulationResult:
    scenario: ScenarioDefinition
    scenario_id: str
    seed: int
    events: tuple[SimulationEvent, ...]
    duplicates_ignored: int = 0

    @property
    def counts(self) -> dict[str, int]:
        return {
            event_type: sum(event.event_type.value == event_type for event in self.events)
            for event_type in sorted({event.event_type.value for event in self.events})
        }


def generate_events(
    scenario: ScenarioDefinition,
    *,
    seed: int,
    clock: SimulationClock,
    sink: SimulationSink | None = None,
) -> SimulationResult:
    scenario_id = f"{scenario.name.lower()}-{seed}"
    previous_offset = None
    events: list[SimulationEvent] = []
    for sequence, step in enumerate(scenario.steps):
        if previous_offset is not None and step.offset < previous_offset:
            raise ValueError("scenario steps must be ordered by simulation time")
        previous_offset = step.offset
        clock.wait_until(step.offset)
        event = SimulationEvent.create(
            scenario_id,
            sequence,
            step.event_type,
            clock.at(step.offset),
            step.payload,
        )
        validate_event(event, clock.start_time, scenario.duration)
        events.append(event)
        if sink is not None:
            sink.emit(event)
    return SimulationResult(scenario, scenario_id, seed, tuple(events))


def build_clock(start_time: datetime, mode: str, speed: float) -> SimulationClock:
    return SimulationClock(start_time=start_time, mode=mode, speed=speed)


def seeded_scenario(name: str, seed: int):
    from .scenarios import get_scenario

    return get_scenario(name, Random(seed))
