from datetime import datetime
from uuid import UUID

from .config import RiskConfig
from .explanations import explain_factors
from .models import EdgeEvidence, EdgeRiskAssessment
from .normalization import age_seconds, clamp01, freshness_weight, normalize_measurement

SEVERITY_SCORE = {"LOW": 0.25, "MODERATE": 0.50, "HIGH": 0.75, "SEVERE": 1.0}
QUALITY_CONFIDENCE = {"GOOD": 1.0, "SUSPECT": 0.5, "SIMULATED": 0.5, "INVALID": 0.0}
STATUS_CONFIDENCE = {"VERIFIED": 1.0, "REPORTED": 0.5}


def _zone_factor(evidence: EdgeEvidence) -> tuple[float, float, float | None]:
    if not evidence.flood_zones:
        return 0.0, 0.0, None
    strongest = max(evidence.flood_zones, key=lambda zone: zone.score)
    return (
        clamp01(strongest.score),
        clamp01(strongest.confidence),
        strongest.evidence_age.total_seconds(),
    )


def _sensor_factors(
    evidence: EdgeEvidence, now: datetime, config: RiskConfig
) -> tuple[float, float, float | None]:
    water_scores = []
    rainfall_scores = []
    ages = []
    confidences = []
    for sensor in evidence.sensors:
        freshness = freshness_weight(sensor.observed_at, now, config.sensor_validity)
        if freshness == 0:
            continue
        quality = QUALITY_CONFIDENCE.get(sensor.quality, 0.0)
        confidence = freshness * quality
        confidences.append(confidence)
        ages.append(age_seconds(sensor.observed_at, now))
        water = normalize_measurement(sensor.water_depth_cm, config.water_depth_thresholds_cm)
        rainfall = normalize_measurement(sensor.rainfall_mm, config.rainfall_thresholds_mm)
        if water is not None:
            water_scores.append(water * freshness)
        if rainfall is not None:
            rainfall_scores.append(rainfall * freshness)
    return (
        max(water_scores, default=0.0),
        max(rainfall_scores, default=0.0),
        min(ages) if ages else None,
    ), max(confidences, default=0.0)


def _weather_factor(
    evidence: EdgeEvidence, now: datetime, config: RiskConfig
) -> tuple[float, float, float | None]:
    scores = []
    confidences = []
    ages = []
    for observation in evidence.weather:
        freshness = freshness_weight(observation.observed_at, now, config.weather_validity)
        if freshness == 0 or observation.rainfall_mm is None:
            continue
        rainfall = observation.rainfall_mm
        if observation.observation_interval_minutes:
            rainfall = rainfall * 60 / observation.observation_interval_minutes
        scores.append(normalize_measurement(rainfall, config.rainfall_thresholds_mm) * freshness)
        confidences.append(freshness)
        ages.append(age_seconds(observation.observed_at, now))
    return max(scores, default=0.0), max(confidences, default=0.0), min(ages) if ages else None


def _prediction_factor(
    evidence: EdgeEvidence, now: datetime, config: RiskConfig
) -> tuple[float, float, float | None]:
    scores = []
    ages = []
    for prediction in evidence.predictions:
        if (
            prediction.predicted_for > now
            or prediction.expires_at is not None
            and prediction.expires_at <= now
        ):
            continue
        probability = clamp01(prediction.probability)
        depth = normalize_measurement(
            prediction.predicted_water_depth_cm, config.water_depth_thresholds_cm
        )
        score = probability if depth is None else max(probability, probability * depth)
        scores.append(score)
        ages.append(age_seconds(prediction.predicted_for, now))
    return max(scores, default=0.0), max(scores, default=0.0), min(ages) if ages else None


def _incident_factor(
    evidence: EdgeEvidence, now: datetime, config: RiskConfig
) -> tuple[float, float, float | None]:
    scores = []
    confidences = []
    ages = []
    for incident in evidence.incidents:
        freshness = freshness_weight(incident.occurred_at, now, config.incident_validity)
        status_confidence = STATUS_CONFIDENCE.get(incident.status, 0.0)
        if freshness == 0 or status_confidence == 0:
            continue
        confidence = clamp01(incident.confidence if incident.confidence is not None else 0.5)
        scores.append(
            SEVERITY_SCORE.get(incident.severity, 0.0) * freshness * status_confidence * confidence
        )
        confidences.append(freshness * status_confidence * confidence)
        ages.append(age_seconds(incident.occurred_at, now))
    return max(scores, default=0.0), max(confidences, default=0.0), min(ages) if ages else None


def risk_level(score: float, config: RiskConfig) -> str:
    low, moderate, high = config.risk_level_thresholds
    if score < low:
        return "LOW"
    if score < moderate:
        return "MODERATE"
    if score < high:
        return "HIGH"
    return "SEVERE"


def assess_edge(
    edge_id: UUID,
    edge_distance_m: float,
    evidence: EdgeEvidence,
    now: datetime,
    config: RiskConfig,
) -> EdgeRiskAssessment:
    flood_zone_score, flood_confidence, zone_age = _zone_factor(evidence)
    sensor_values, sensor_confidence = _sensor_factors(evidence, now, config)
    water_depth_score, sensor_rainfall_score, sensor_age = sensor_values
    weather_score, weather_confidence, weather_age = _weather_factor(evidence, now, config)
    prediction_score, prediction_confidence, prediction_age = _prediction_factor(
        evidence, now, config
    )
    incident_score, incident_confidence, incident_age = _incident_factor(evidence, now, config)
    factors = {
        "flood_zone": flood_zone_score,
        "water_depth": water_depth_score,
        "rainfall": max(sensor_rainfall_score, weather_score),
        "prediction": prediction_score,
        "incident": incident_score,
    }
    weights = config.normalized_weights
    score = clamp01(sum(weights[name] * value for name, value in factors.items()))
    if water_depth_score >= 0.9 or flood_zone_score >= 0.9:
        score = max(score, 0.75)
    confidences = {
        "flood_zone": flood_confidence,
        "water_depth": sensor_confidence,
        "rainfall": max(sensor_confidence, weather_confidence),
        "prediction": prediction_confidence,
        "incident": incident_confidence,
    }
    confidence = clamp01(sum(weights[name] * value for name, value in confidences.items()))
    ages = [
        age
        for age in (zone_age, sensor_age, weather_age, prediction_age, incident_age)
        if age is not None
    ]
    return EdgeRiskAssessment(
        edge_id=edge_id,
        risk_score=score,
        risk_level=risk_level(score, config),
        confidence=confidence,
        flood_zone_score=flood_zone_score,
        water_depth_score=water_depth_score,
        rainfall_score=factors["rainfall"],
        prediction_score=prediction_score,
        incident_score=incident_score,
        evidence_age_seconds=min(ages) if ages else None,
        explanation=explain_factors(
            flood_zone_score=flood_zone_score,
            water_depth_score=water_depth_score,
            rainfall_score=factors["rainfall"],
            prediction_score=prediction_score,
            incident_score=incident_score,
            confidence=confidence,
        ),
        high_risk_distance_m=edge_distance_m if score >= 0.5 else 0.0,
    )
