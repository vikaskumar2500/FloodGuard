# Phase 6 deterministic risk engine

Phase 6 adds environmental risk as a separate, deterministic layer over the versioned directed road graph. Live risk is never stored on `road_edges`. The engine bulk-loads evidence, evaluates one in-memory `RiskSnapshot`, prepares an O(1) risk map, and passes nonnegative edge costs to the generic Dijkstra/A* algorithms.

## Evidence architecture

`RiskEvidenceRepository` performs bulk PostGIS queries for the selected graph edges:

- Active `FloodZone` intersections
- Recent `SensorEvent` observations within 250 m
- Recent `WeatherObservation` records within 1,000 m
- Active direct or intersecting `FloodPrediction` records
- Recent `REPORTED` or `VERIFIED` `Incident` records within 250 m

There are five evidence queries, not one query per edge relaxation. Scoring is independent of SQLAlchemy and can run entirely in unit tests with `EdgeEvidence` objects.

## Factors and configuration

Default normalized weights are:

| Factor | Weight |
| --- | ---: |
| Flood zone | 0.35 |
| Water depth | 0.30 |
| Rainfall | 0.10 |
| Prediction | 0.15 |
| Incident | 0.10 |

Weights are validated as finite, nonnegative, and normalized at use time. Risk levels are `LOW < 0.25`, `MODERATE < 0.50`, `HIGH < 0.75`, and `SEVERE >= 0.75`.

Water-depth thresholds are 5, 15, 30, and 50 cm. Rainfall thresholds are 5, 15, 30, and 50 mm/hour. These are deterministic engineering/demo assumptions, not calibrated scientific thresholds. Measurements are finite, nonnegative, piecewise normalized to `[0, 1]`, and invalid values are rejected.

The default cost scales are configurable through settings: balanced penalty 120 seconds per unit risk, safest penalty 900 seconds per unit risk, and safest unknown-evidence penalty 60 seconds times `(1 - confidence)`. Spatial radii and evidence windows are centralized in `RiskConfig`.

## Risk formula

For edge $e$, each factor $r_i(e)$ is normalized into $[0,1]` and the configured weights are normalized to sum to one:

$$
R(e) = \operatorname{clamp}_{[0,1]}\left(\sum_i w_i r_i(e)\right)
$$

A severe flood-zone or water-depth signal applies a floor of `HIGH` (`0.75`). Confidence is calculated separately from evidence quality, freshness, verification state, and prediction strength. No evidence yields risk `0` with confidence `0`, and is explained as unknown rather than safe.

## Temporal semantics

- Flood zones are filtered by `valid_from <= now` and `valid_until > now` when present.
- Sensors are valid for two hours; freshness decreases linearly to zero.
- Weather observations are valid for three hours; rainfall is converted to hourly intensity when an interval exists.
- Incidents are valid for 24 hours, and only `REPORTED`/`VERIFIED` incidents contribute.
- Predictions must have `predicted_for <= now` and not be expired.
- Future-dated observations are ignored.

All evaluation uses one injected/reference UTC timestamp per snapshot. The current service creates one UTC timestamp before evidence retrieval.

## Routing costs

Let $T(e)$ be persisted baseline travel time and $R(e)$ the risk score:

$$
C_{FASTEST}(e) = T(e)
$$

$$
C_{BALANCED}(e) = T(e) + 120R(e)
$$

$$
C_{SAFEST}(e) = T(e) + 900R(e) + 60(1 - confidence(e))
$$

Actual penalty settings are configurable. All penalties are nonnegative, so the Phase 5 baseline A* heuristic remains admissible:

$$
h_{baseline}(n) \leq \text{remaining baseline cost} \leq \text{remaining risk-aware cost}
$$

FASTEST still calculates risk for reporting but does not use it in optimization. BALANCED and SAFEST use risk-aware costs. No hard blocking threshold is enabled; a severe route remains available when no alternative exists.

## Route risk output

The API returns aggregate `riskScore`, `riskLevel`, `riskConfidence`, `maxEdgeRisk`, and `highRiskDistanceMeters`. It also returns risk segments with edge ID, score, level, confidence, explanation, and directed LineString geometry. Route risk is distance-weighted average risk, not the sum of cost penalties. Segment risk is persisted in nullable `route_segments.risk_score` and structured metadata.

Explanations are deterministic, for example: `Risk is influenced by active flood-zone evidence, recent rainfall; confidence is 78%.` No LLM or ML model is involved.

## Limitations

The engine does not implement ML, live event processing, route invalidation, traffic, turn restrictions, conditional access, weather-provider ingestion, Redis caching, or real-time rerouting. Existing Phase 4 real-region persistence and Phase 5 PostGIS verification remain dependent on the unavailable local infrastructure.
