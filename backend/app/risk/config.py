from dataclasses import dataclass, field
from datetime import timedelta
from math import isfinite


@dataclass(frozen=True)
class RiskConfig:
    flood_zone_weight: float = 0.35
    water_depth_weight: float = 0.30
    rainfall_weight: float = 0.10
    prediction_weight: float = 0.15
    incident_weight: float = 0.10
    balanced_penalty_seconds: float = 120.0
    safest_penalty_seconds: float = 900.0
    safest_unknown_penalty_seconds: float = 60.0
    sensor_validity: timedelta = field(default=timedelta(hours=2))
    weather_validity: timedelta = field(default=timedelta(hours=3))
    incident_validity: timedelta = field(default=timedelta(hours=24))
    sensor_radius_m: float = 250.0
    weather_radius_m: float = 1_000.0
    incident_radius_m: float = 250.0
    risk_level_thresholds: tuple[float, float, float] = (0.25, 0.50, 0.75)
    water_depth_thresholds_cm: tuple[float, float, float, float] = (5.0, 15.0, 30.0, 50.0)
    rainfall_thresholds_mm: tuple[float, float, float, float] = (5.0, 15.0, 30.0, 50.0)

    def __post_init__(self) -> None:
        weights = (
            self.flood_zone_weight,
            self.water_depth_weight,
            self.rainfall_weight,
            self.prediction_weight,
            self.incident_weight,
        )
        if any(not isfinite(weight) or weight < 0 for weight in weights):
            raise ValueError("risk weights must be finite and nonnegative")
        if not isfinite(sum(weights)) or sum(weights) <= 0:
            raise ValueError("risk weights must have a positive total")
        if any(
            not isfinite(value) or value < 0
            for value in (
                self.balanced_penalty_seconds,
                self.safest_penalty_seconds,
                self.safest_unknown_penalty_seconds,
                self.sensor_radius_m,
                self.weather_radius_m,
                self.incident_radius_m,
            )
        ):
            raise ValueError("risk penalty scales must be finite and nonnegative")
        if (
            not 0
            <= self.risk_level_thresholds[0]
            < self.risk_level_thresholds[1]
            < self.risk_level_thresholds[2]
            <= 1
        ):
            raise ValueError("risk level thresholds must be increasing within [0, 1]")
        if any(
            not isfinite(value) or value <= 0
            for value in (*self.water_depth_thresholds_cm, *self.rainfall_thresholds_mm)
        ):
            raise ValueError("normalization thresholds must be positive and finite")
        if (
            self.sensor_validity <= timedelta(0)
            or self.weather_validity <= timedelta(0)
            or self.incident_validity <= timedelta(0)
        ):
            raise ValueError("evidence validity windows must be positive")

    @property
    def normalized_weights(self) -> dict[str, float]:
        total = sum(
            (
                self.flood_zone_weight,
                self.water_depth_weight,
                self.rainfall_weight,
                self.prediction_weight,
                self.incident_weight,
            )
        )
        return {
            "flood_zone": self.flood_zone_weight / total,
            "water_depth": self.water_depth_weight / total,
            "rainfall": self.rainfall_weight / total,
            "prediction": self.prediction_weight / total,
            "incident": self.incident_weight / total,
        }
