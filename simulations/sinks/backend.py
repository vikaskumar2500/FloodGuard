import json
from collections.abc import Callable
from urllib.request import Request, urlopen

from simulations.models import SimulationEvent


class BackendSink:
    """Explicit development adapter; it never silently falls back to local output."""

    def __init__(
        self, endpoint: str, sender: Callable[[SimulationEvent], None] | None = None
    ) -> None:
        self.endpoint = endpoint
        self.sender = sender
        self.events_emitted = 0
        self.duplicates = 0

    def emit(self, event: SimulationEvent) -> None:
        if self.sender is not None:
            self.sender(event)
        else:
            request = Request(
                self.endpoint,
                data=json.dumps(event.to_dict()).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                if response.status >= 400:
                    raise RuntimeError(f"simulation backend rejected event: {response.status}")
                result = json.loads(response.read().decode("utf-8"))
                if result.get("accepted") is not True:
                    raise RuntimeError("simulation backend did not accept event")
                if result.get("duplicate") is True:
                    self.duplicates += 1
        self.events_emitted += 1

    def close(self) -> None:
        return None
