from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic, sleep


@dataclass
class SimulationClock:
    start_time: datetime
    mode: str = "immediate"
    speed: float = 1.0

    def __post_init__(self) -> None:
        if self.start_time.tzinfo is None:
            raise ValueError("simulation start time must be timezone-aware")
        if self.mode not in {"immediate", "timed"}:
            raise ValueError("simulation clock mode must be immediate or timed")
        if self.speed <= 0:
            raise ValueError("simulation clock speed must be positive")
        self._wall_started: float | None = None

    def at(self, offset: timedelta) -> datetime:
        if offset < timedelta(0):
            raise ValueError("simulation offset cannot be negative")
        return self.start_time + offset

    def wait_until(self, offset: timedelta) -> None:
        if self.mode == "immediate":
            return
        if self._wall_started is None:
            self._wall_started = monotonic()
        target_seconds = offset.total_seconds() / self.speed
        elapsed = monotonic() - self._wall_started
        if target_seconds > elapsed:
            sleep(target_seconds - elapsed)
