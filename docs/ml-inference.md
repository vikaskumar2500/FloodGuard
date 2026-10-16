# ML Inference & Routing Integration Architecture (Phase 13)

> **SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.**  
> *The machine learning models used in this system were trained and evaluated exclusively on synthetic simulation datasets (`v1-3df12444-3a440b39`). Real-world historical sensor calibration is currently blocked pending PostGIS archive ingestion. Consequently, ML predictions are strictly additive and advisory.*

---

## 1. Overview & Core Invariants

Phase 13 integrates the Phase 12 XGBoost flood prediction model (`xgboost-v1`) into FloodGuard's deterministic risk engine and A*/Dijkstra routing pipeline. The system enforces 5 critical invariants to guarantee that safety, system reliability, and algorithmic performance are never compromised:

1. **CRITICAL INVARIANT 1: Safety Asymmetry ($R_{\text{fused}} \ge R_{\text{det}}$)**  
   Machine learning predictions can **never** reduce or downgrade a stronger deterministic physical risk assessment. ML is strictly additive and proactive. Critical physical flood evidence (e.g. water depth $\ge 15.0$ cm, high-risk flood polygons) always overrides lower ML probabilities.
2. **CRITICAL INVARIANT 2: Graceful Degradation / Failure Fallback**  
   Model inference errors, timeouts, corrupt artifacts, or schema anomalies must **never** block route computation. Any ML failure immediately degrades to the Phase 6 deterministic physical risk assessment.
3. **CRITICAL INVARIANT 3: Zero Inference in Graph Relaxation Loops**  
   Model inference is **never** invoked inside the inner Dijkstra/A* relaxation loop. All edge predictions for candidate graph bounds are precomputed in batch prior to graph search, ensuring $O(1)$ constant-time edge cost lookups during exploration.
4. **CRITICAL INVARIANT 4: Zero Training-Serving Skew**  
   The online feature builder (`OnlineFeatureBuilder`) directly reuses the canonical feature engineering routines from Phase 11 (`floodguard_ml.features.*`), computing the exact 29 canonical model features (`MODEL_FEATURES_V1`) without future leakage or proxy attributes.
5. **CRITICAL INVARIANT 5: Explicit Synthetic Provenance**  
   All ML-derived outputs, metadata, API payloads, and UI summaries explicitly communicate the synthetic data provenance to prevent operator overconfidence.

---

## 2. End-to-End Pipeline Architecture

```mermaid
flowchart TD
    subgraph Evidence Layer
        Sensors["Water Level Sensors"]
        Rainfall["Weather / Rainfall Observations"]
        Polygons["Flood Hazard Polygons"]
    end

    subgraph Feature Engineering
        Evidence Layer --> OFB["OnlineFeatureBuilder (v1)"]
        RoadGraph["RoutingGraph (Road Topography)"] --> OFB
        OFB --> CanonicalFeatures["29 Canonical Features (MODEL_FEATURES_V1)"]
    end

    subgraph ML Inference & Caching
        CanonicalFeatures --> MLCache{"Redis ML Cache (ml_prediction_key)"}
        MLCache -- "HIT" --> PrecomputedPreds["Batch Predictions"]
        MLCache -- "MISS" --> BoundedBatch["Bounded Batching (max 512 edges)"]
        BoundedBatch --> ModelExec["asyncio.to_thread(LoadedFloodModel.predict_proba)"]
        ModelExec --> SetCache["Redis set_batch (TTL 300s)"]
        SetCache --> PrecomputedPreds
        ModelExec -. "Timeout / Exception" .-> FallbackEmpty["Empty Predictions (Fallback)"]
        FallbackEmpty --> PrecomputedPreds
    end

    subgraph Risk Fusion Layer
        DetEngine["Deterministic Risk Engine (Phase 6)"] --> DetAssessments["Deterministic Edge Assessments (R_det)"]
        DetAssessments & PrecomputedPreds --> Fusion["RiskFusionService.fuse_edge()"]
        Fusion --> FusionRule{"Mode Decision"}
        FusionRule -- "DISABLED" --> OutDet["R_fused = R_det"]
        FusionRule -- "SHADOW" --> OutShadow["R_fused = R_det + Log Telemetry & Disagreements"]
        FusionRule -- "ACTIVE" --> OutActive["R_fused = max(R_det, (1-α)R_det + α*P_ml) + Safety Overrides"]
    end

    subgraph Graph Search
        OutDet & OutShadow & OutActive --> EdgeCost["Edge Cost Multiplier Calculation"]
        EdgeCost --> AStar["A* / Dijkstra Shortest Path Search (O(1) lookups)"]
        AStar --> RouteResult["RouteCalculationResponse + ML Telemetry"]
    end
```

---

## 3. Operational Integration Modes

FloodGuard supports three operational integration modes via the `ML_MODE` configuration setting:

| Mode | Routing Influence | Telemetry & UI | Disagreement Monitoring | Use Case |
| :--- | :--- | :--- | :--- | :--- |
| `DISABLED` | None ($R_{\text{fused}} = R_{\text{det}}$) | ML metadata omitted | Inactive | Minimal resource environments, testing baseline routing. |
| `SHADOW` *(Default)* | None ($R_{\text{fused}} = R_{\text{det}}$) | Emits ML probabilities & diagnostics | Logs high ML / low physical and low ML / high physical divergences | Observational validation without operational risk. |
| `ACTIVE` | Fused ($R_{\text{fused}} \ge R_{\text{det}}$) | Full ML telemetry & route cost penalties | Active | Proactive avoidance of impending flood hazards. |

### Configuration Parameters

In `backend/app/core/config.py`:
- `ML_ENABLED`: Master toggle (`true`/`false`). Default: `true`.
- `ML_MODE`: Mode string (`DISABLED`, `SHADOW`, `ACTIVE`). Default: `"SHADOW"`.
- `ML_MODEL_PATH`: Directory containing the model artifacts. Default: `ml/artifacts/xgboost-v1`.
- `ML_MODEL_VERSION`: Active model tag. Default: `"xgboost-v1"`.
- `ML_RISK_WEIGHT` ($\alpha$): Blending weight for active mode. Default: `0.35` (clamped to $[0.0, 1.0]$).
- `ML_MAX_INFERENCE_BATCH_SIZE`: Maximum chunk size per inference call. Default: `512`.
- `ML_INFERENCE_TIMEOUT_MS`: Hard deadline per batch inference. Default: `500` ms.
- `ML_PREDICTION_CACHE_TTL_SECONDS`: Redis cache duration. Default: `300` s (5 minutes).

---

## 4. Online Feature Extraction & Parity

To eliminate training-serving skew, `OnlineFeatureBuilder` directly invokes the canonical Phase 11 feature generators:

1. **Temporal Features**: `compute_temporal_features(now)` (hour, day of week, sine/cosine cyclical transforms).
2. **Road Geometry Features**: `compute_road_features(edge)` (length, max speed, lanes, bridge/tunnel flags, surface category).
3. **Sensor Features**: `compute_sensor_features(sensor_records, now)` (water depth max/mean/rate of change, freshness, quality).
4. **Rainfall Features**: `compute_rainfall_features(weather_records, now)` (accumulations over 15m, 30m, 1h, 3h, 6h, peak rates).
5. **Missingness & Indicators**: `compute_missingness_indicators()` and `compute_historical_features()`.

### Feature Leakage Audit
`OnlineFeatureBuilder` enforces strict non-leakage rules:
- Observations timestamped $> now$ are rejected.
- Target variables (`target_flooded_within_horizon`), raw row IDs, and database keys are excluded.
- Evaluates exactly the 29 features required by `MODEL_FEATURES_V1`.

---

## 5. Model Serving & Lifecycle Management

### 5.1. Startup Initialization & Verification
During FastAPI application startup lifespan (`backend/app/main.py`):
1. **Artifact Loading**: `LoadedFloodModel.load(settings.ml_model_path)` deserializes the pipeline binary, metadata, and decision threshold.
2. **SHA-256 Checksum Validation**: Computes `sha256` of `model.joblib` and validates it against recorded metadata. Corrupted or tampered files trigger `ModelIntegrityError` and abort startup.
3. **Warm-up Inference**: Executes a test batch of synthetic features to pre-warm JIT compilers and CPU caches.
4. **Runtime Registration**: Attaches `LoadedFloodModel` to `FloodPredictionService` and `RiskFusionService`.

### 5.2. Bounded Batch Inference & Timeout Protection
- Requests are partitioned into chunks of size $\le 512$ (`ml_max_inference_batch_size`).
- Model inference is offloaded to worker threads via `asyncio.to_thread` to preserve the FastAPI event loop responsiveness.
- Wrapped in `asyncio.wait_for` with a `500 ms` deadline (`ml_inference_timeout_ms`).
- In the event of a timeout or model error, a structured warning is logged, error metrics are incremented, and unpredicted edges default safely to deterministic evaluation.

---

## 6. Redis ML Prediction Cache

ML predictions are cached at the edge level to accelerate repeated queries:

### Canonical Cache Key Pattern
```text
floodguard:v1:ml-prediction:{graph_version_id}:{model_version}:{risk_revision}:{edge_id}:{config_hash}
```

- **`graph_version_id`**: Isolates predictions across road network imports.
- **`model_version`**: Ensures automatic cache invalidation upon model rollback or upgrade.
- **`risk_revision`**: When an environmental simulation step or sensor event advances the risk revision (e.g., from `R1` to `R2`), all old edge prediction keys become cache misses automatically without expensive Redis `SCAN` operations.
- **`edge_id`**: Fine-grained edge identification.
- **`config_hash`**: Captures ML parameters ($\alpha$, threshold) ensuring instant freshness on configuration changes.

### Pipeline Efficiency & Outage Resilience
- **Batch Operations**: Uses Redis pipeline commands (`pipe.get()`, `pipe.setex()`) to fetch and store hundreds of edge predictions in a single network round-trip.
- **Redis Outages**: If Redis disconnects or errors, the cache logs a warning, returns a cache miss, and routes proceed unimpeded.

---

## 7. Risk Fusion Mathematical Formulation

### Fusion Equation (ACTIVE Mode)
For an edge $e$ with deterministic risk $R_{\text{det}} \in [0.0, 1.0]$ and ML flood probability $P_{\text{ml}} \in [0.0, 1.0]$:

$$R_{\text{blended}} = (1 - \alpha) \cdot R_{\text{det}} + \alpha \cdot P_{\text{ml}}$$

$$R_{\text{fused}} = \max\left(R_{\text{det}}, \, R_{\text{blended}}\right)$$

Where $\alpha \in [0.0, 1.0]$ is the configured `ml_risk_weight` (default $0.35$).

### Critical Physical Evidence Floor
If edge $e$ exhibits any of the following critical physical conditions:
- Direct sensor water depth $\ge 15.0$ cm ($\text{water\_depth\_score} \ge 0.75$)
- Severe flood zone polygon intersection ($\text{flood\_zone\_score} \ge 0.75$)
- Deterministic risk $R_{\text{det}} \ge 0.75$ or deterministic level $\in \{\text{HIGH}, \text{SEVERE}\}$

Then the fused risk level is **hard-pinned**:

$$\text{Level}_{\text{fused}} \ge \text{Level}_{\text{det}}$$

$$R_{\text{fused}} \ge R_{\text{det}}$$

Under no circumstance can a low ML probability ($P_{\text{ml}} \approx 0$) downgrade a flooded road to passable.

### Non-Negative Edge Cost & A* Admissibility
The routing cost multiplier for edge $e$ with travel time $t_e$ and fused risk $R_{\text{fused}}$ is:

$$\text{Cost}(e) = t_e \cdot \left(1.0 + \text{Penalty}_{\text{mode}} \cdot R_{\text{fused}}\right)$$

Because $R_{\text{fused}} \ge 0$ and $\text{Penalty}_{\text{mode}} \ge 0$, $\text{Cost}(e) \ge t_e > 0$. The Euclidean distance heuristic remains admissible and monotonic for A* path search.

---

## 8. Latency & Performance Profile

Benchmarked across route computations on the 4-node reference road network:

| Component | Cold Miss Latency | Warm Cache Latency | Description |
| :--- | :--- | :--- | :--- |
| **Feature Extraction** | $0.148\text{ ms}$ ($0.037\text{ ms}$/edge) | N/A (bypassed on hit) | 29-feature construction from live evidence. |
| **Batch Inference** | $13.68\text{ ms}$ (total chunk) | N/A (bypassed on hit) | XGBoost thread inference across edges. |
| **Redis Cache Lookup** | N/A | $0.108\text{ ms}$ | Redis batch pipeline fetch. |
| **Risk Fusion Layer** | $0.049\text{ ms}$ | $0.049\text{ ms}$ | Asymmetric safety blend & explanation builder. |
| **Total Added Overhead** | $\mathbf{13.88\text{ ms}}$ | $\mathbf{0.157\text{ ms}}$ | Minimal latency impact during routing. |

A* inner-loop edge evaluation latency remains **$O(1)$** because edge risk values are stored in a precomputed lookup map prior to graph exploration.

---

## 9. Observability & Telemetry

### Shadow Disagreement Diagnostics
In `SHADOW` mode, divergences between ML predictions and deterministic physical observations are automatically logged as structured events (`ml_shadow_disagreement`):
1. **`ML_HIGH_DETERMINISTIC_LOW`**: $P_{\text{ml}} \ge 0.80$ while deterministic evidence is dry/minimal. Indicates potential early-warning capability or false positive.
2. **`ML_LOW_DETERMINISTIC_HIGH`**: $P_{\text{ml}} \le 0.20$ while critical physical water depth is present. Indicates potential false negative or model blind spot.

### API Response Envelope
Route calculation responses include dedicated ML metadata:

```json
{
  "routeId": "7b82f05c-3f92-4f10-91a3-28f0de20da1e",
  "status": "CALCULATED",
  "ml": {
    "enabled": true,
    "mode": "SHADOW",
    "modelVersion": "xgboost-v1",
    "featureVersion": "v1",
    "riskWeight": 0.35,
    "predictionsCount": 4,
    "provenanceWarning": "SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy."
  },
  "riskSegments": [
    {
      "edgeId": "8b51d624-9b25-4c07-b2f5-d018eead8259",
      "riskScore": 0.12,
      "riskLevel": "LOW",
      "deterministicRisk": 0.12,
      "mlProbability": 0.15,
      "fusedRisk": 0.12,
      "explanation": "Road edge is outside high-risk flood polygons..."
    }
  ]
}
```

