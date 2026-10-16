import json
from pathlib import Path

from simulations.models import SimulationEvent


class FileSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", encoding="utf-8")
        self._event_ids: set[str] = set()
        self.duplicates_ignored = 0

    def emit(self, event: SimulationEvent) -> None:
        event_id = str(event.event_id)
        if event_id in self._event_ids:
            self.duplicates_ignored += 1
            return
        self._event_ids.add(event_id)
        self._handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()
