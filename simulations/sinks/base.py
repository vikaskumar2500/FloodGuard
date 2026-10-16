from typing import Protocol

from simulations.models import SimulationEvent


class SimulationSink(Protocol):
    def emit(self, event: SimulationEvent) -> None: ...

    def close(self) -> None: ...
