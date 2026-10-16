from simulations.models import SimulationEvent


class MemorySink:
    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []
        self._event_ids: set[str] = set()
        self.duplicates_ignored = 0

    def emit(self, event: SimulationEvent) -> None:
        event_id = str(event.event_id)
        if event_id in self._event_ids:
            self.duplicates_ignored += 1
            return
        self._event_ids.add(event_id)
        self.events.append(event)

    def close(self) -> None:
        return None
